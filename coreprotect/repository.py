"""CoreProtect is external and read-only. Never register it in Django DATABASES."""

import re
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from typing import Protocol

import pymysql
from django.conf import settings

from .mining import (
    DIAMOND_MATERIALS,
    DiamondQuery,
    DiamondStatsRow,
    MaterialBreakRow,
    OreGroup,
    player_record_predicate,
)
from .rollup import MiningBatch, MiningBucket


class CoreProtectUnavailable(Exception):
    pass


@dataclass(frozen=True)
class World:
    id: int
    name: str


class CoreProtectRepository(Protocol):
    def check_connection(self) -> bool: ...
    def get_version(self) -> str | None: ...
    def list_worlds(self) -> list[World]: ...
    def resolve_world(self, name: str) -> World | None: ...
    def resolve_material(self, name: str) -> int | None: ...
    def get_diamond_stats(self, query: DiamondQuery) -> tuple[DiamondStatsRow, ...]: ...
    def get_denominator_stats(
        self, query: DiamondQuery, group: OreGroup
    ) -> tuple[MaterialBreakRow, ...]: ...
    def get_material_stats(
        self, query, materials, *, natural_only
    ) -> tuple[MaterialBreakRow, ...]: ...
    def mining_high_water(self) -> int: ...
    def read_mining_batch(self, after, through, batch_size, materials) -> MiningBatch: ...
    def read_mining_day(self, day, through, materials) -> tuple[MiningBucket, ...]: ...


def configured():
    return all(
        [
            settings.COREPROTECT_DB_HOST,
            settings.COREPROTECT_DB_NAME,
            settings.COREPROTECT_DB_USER,
            settings.COREPROTECT_DB_PASSWORD,
        ]
    )


class MariaDBCoreProtectRepository:
    def __init__(self):
        self.prefix = settings.COREPROTECT_TABLE_PREFIX
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", self.prefix):
            raise CoreProtectUnavailable("Invalid CoreProtect table prefix.")

    @contextmanager
    def _cursor(self):
        if not configured():
            raise CoreProtectUnavailable("CoreProtect is not configured.")
        timeout = settings.COREPROTECT_TIMEOUT_SECONDS
        try:
            with closing(
                pymysql.connect(
                    host=settings.COREPROTECT_DB_HOST,
                    port=settings.COREPROTECT_DB_PORT,
                    database=settings.COREPROTECT_DB_NAME,
                    user=settings.COREPROTECT_DB_USER,
                    password=settings.COREPROTECT_DB_PASSWORD,
                    charset="utf8mb4",
                    connect_timeout=timeout,
                    read_timeout=timeout,
                    write_timeout=timeout,
                    autocommit=False,
                    local_infile=False,
                )
            ) as connection:
                with connection.cursor() as cursor:
                    # MariaDB 10.3 supports both. These change only this short-lived session.
                    cursor.execute("SET SESSION max_statement_time = %s", (timeout,))
                    cursor.execute("START TRANSACTION READ ONLY")
                    try:
                        yield cursor
                    finally:
                        connection.rollback()
        except (pymysql.MySQLError, OSError, ValueError, TypeError, KeyError):
            raise CoreProtectUnavailable(
                "CoreProtect is unavailable. Contact a portal owner."
            ) from None

    def check_connection(self) -> bool:
        with self._cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)

    def get_version(self) -> str | None:
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT version FROM `{self.prefix}version` ORDER BY rowid DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return str(row[0]) if row else None

    def list_worlds(self) -> list[World]:
        with self._cursor() as cursor:
            cursor.execute(f"SELECT id, world FROM `{self.prefix}world` ORDER BY id LIMIT 1001")
            rows = cursor.fetchall()
            if len(rows) > 1000:
                raise CoreProtectUnavailable("World mapping exceeds the diagnostic display limit.")
            return [World(int(row[0]), str(row[1])) for row in rows]

    def resolve_world(self, name: str) -> World | None:
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT id, world FROM `{self.prefix}world` WHERE world = %s LIMIT 1",
                (name,),
            )
            row = cursor.fetchone()
            return World(int(row[0]), str(row[1])) if row else None

    def resolve_material(self, name: str) -> int | None:
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM `{self.prefix}material_map` WHERE material = %s LIMIT 1",
                (name,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else None

    def get_diamond_stats(self, query: DiamondQuery) -> tuple[DiamondStatsRow, ...]:
        rows = self.get_material_stats(query, DIAMOND_MATERIALS, natural_only=True)
        return tuple(DiamondStatsRow(row.player_uuid, row.player_name, *row.counts) for row in rows)

    def get_denominator_stats(self, query: DiamondQuery, group: OreGroup):
        return self.get_material_stats(query, group.denominator_materials, natural_only=False)

    def get_material_stats(self, query, materials, *, natural_only):
        """Reusable aggregate for a code-defined material group; never accepts SQL fragments."""
        if not materials or len(set(materials)) != len(materials):
            raise CoreProtectUnavailable("Invalid material group.")
        with self._cursor() as cursor:
            placeholders = ", ".join("%s" for _ in materials)
            cursor.execute(
                f"SELECT material, id FROM `{self.prefix}material_map` "
                f"WHERE material IN ({placeholders})",
                tuple(materials),
            )
            mappings = cursor.fetchall()
            resolved = {str(name): int(identifier) for name, identifier in mappings}
            if (
                len(mappings) != len(materials)
                or set(resolved) != set(materials)
                or len(set(resolved.values())) != len(materials)
            ):
                raise CoreProtectUnavailable("Material mappings are unavailable.")
            ids = tuple(resolved[name] for name in materials)
            sql, parameters = self._aggregate_statement(query, ids, natural_only=natural_only)
            cursor.execute(sql, parameters)
            return tuple(
                MaterialBreakRow(
                    str(row[0]),
                    str(row[1]),
                    tuple(int(n) for n in (row[2:-1] if natural_only else row[2:])),
                )
                for row in cursor.fetchall()
            )

    def mining_high_water(self):
        with self._cursor() as cursor:
            cursor.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM `{self.prefix}block`")
            return int(cursor.fetchone()[0])

    def _rollup_material_ids(self, cursor, materials):
        if not materials or len(set(materials.values())) != len(materials):
            raise CoreProtectUnavailable("Invalid rollup materials.")
        placeholders = ", ".join("%s" for _ in materials)
        cursor.execute(
            f"SELECT material, id FROM `{self.prefix}material_map` "
            f"WHERE material IN ({placeholders})",
            tuple(materials.values()),
        )
        rows = cursor.fetchall()
        resolved = {str(name): int(identifier) for name, identifier in rows}
        if (
            len(rows) != len(materials)
            or set(resolved) != set(materials.values())
            or len(set(resolved.values())) != len(materials)
        ):
            raise CoreProtectUnavailable("Rollup material mappings unavailable.")
        return {resolved[name]: key for key, name in materials.items()}

    def read_mining_batch(self, after, through, batch_size, materials):
        if not 0 <= after <= through or not 1 <= batch_size <= 50000:
            raise ValueError("Invalid mining batch bounds.")
        with self._cursor() as cursor:
            ids = self._rollup_material_ids(cursor, materials)
            # Bound work by actual primary-key rows, including irrelevant events and gaps.
            cursor.execute(
                f"SELECT rowid FROM `{self.prefix}block` WHERE rowid > %s AND rowid <= %s "
                "ORDER BY rowid LIMIT %s",
                (after, through, batch_size),
            )
            rowids = cursor.fetchall()
            end = int(rowids[-1][0]) if len(rowids) == batch_size else through
            buckets = self._read_rollup_counts(
                cursor, ids, "b.rowid > %s AND b.rowid <= %s", (after, end), "PRIMARY"
            )
            return MiningBatch(end, buckets)

    def read_mining_day(self, day, through, materials):
        start = datetime.combine(day, time.min, UTC)
        end = start + timedelta(days=1)
        with self._cursor() as cursor:
            ids = self._rollup_material_ids(cursor, materials)
            return self._read_rollup_counts(
                cursor,
                ids,
                "b.time >= %s AND b.time < %s AND b.rowid <= %s",
                (int(start.timestamp()), int(end.timestamp()), through),
                "type",
            )

    def _read_rollup_counts(self, cursor, ids, bounds, parameters, index):
        # All fragments are private constants; only values come from callers/mappings.
        player_sql, player_params = player_record_predicate("u")
        placeholders = ", ".join("%s" for _ in ids)
        sql = f"""
            SELECT base.day_number, LOWER(REPLACE(u.uuid, '-', '')) AS player_uuid,
                   base.wid, base.type, SUM(base.break_count)
            FROM (
                SELECT FLOOR(b.time / 86400) AS day_number, b.user, b.wid, b.type,
                       COUNT(b.rowid) AS break_count
                FROM `{self.prefix}block` b FORCE INDEX (`{index}`)
                WHERE {bounds} AND b.type IN ({placeholders})
                  AND b.action = 0 AND b.rolled_back = 0
                GROUP BY FLOOR(b.time / 86400), b.user, b.wid, b.type
                ORDER BY NULL
            ) base
            STRAIGHT_JOIN `{self.prefix}user` u ON u.rowid = base.user
            WHERE {player_sql}
            GROUP BY base.day_number, LOWER(REPLACE(u.uuid, '-', '')), base.wid, base.type
            ORDER BY NULL
        """
        cursor.execute(sql, tuple(parameters) + tuple(ids) + player_params)
        return tuple(
            MiningBucket(
                date(1970, 1, 1) + timedelta(days=int(day)),
                str(uuid),
                int(world),
                ids[int(material)],
                int(count),
            )
            for day, uuid, world, material, count in cursor.fetchall()
        )

    def _diamond_statement(self, query, diamond, deepslate):
        return self._aggregate_statement(query, (diamond, deepslate), natural_only=True)

    def _aggregate_statement(self, query, material_ids, *, natural_only):
        breaker_sql, breaker_params = player_record_predicate("u")
        placer_sql, placer_params = player_record_predicate("placer")
        placeholders = ", ".join("%s" for _ in material_ids)
        constraints = [f"b.type IN ({placeholders})", "b.action = 0", "b.rolled_back = 0"]
        parameters = [*material_ids, *material_ids]
        if query.start is not None:
            constraints.append("b.time >= %s")
            parameters.append(ceil(query.start.timestamp()))
        if query.end is not None:
            constraints.append("b.time < %s")
            parameters.append(ceil(query.end.timestamp()))
        if query.world_id is not None:
            constraints.append("b.wid = %s")
            parameters.append(query.world_id)
        # b is first so (type,time) narrows rare candidates before user lookups. In the
        # anti-lookup (wid,x,z,time) narrows placements; y/type/order finish the match.
        # Do not add reporting-window bounds to p: older placements must still exclude.
        columns = ", ".join(
            f"SUM(CASE WHEN b.type = %s THEN 1 ELSE 0 END) AS count_{i}"
            for i in range(len(material_ids))
        )
        if not natural_only:
            # Reduce millions of events to user-ID totals before any player lookups.
            # The outer aggregate combines historical user IDs sharing a normalized UUID.
            totals = ", ".join(
                f"SUM(base.count_{i}) AS count_{i}" for i in range(len(material_ids))
            )
            sql = f"""
                SELECT LOWER(REPLACE(u.uuid, '-', '')) AS player_uuid,
                       MIN(u.user) AS player_name, {totals}
                FROM (
                    SELECT b.user, {columns}
                    FROM `{self.prefix}block` b FORCE INDEX (`type`)
                    WHERE {" AND ".join(constraints)}
                    GROUP BY b.user
                    ORDER BY NULL
                ) base
                STRAIGHT_JOIN `{self.prefix}user` u ON u.rowid = base.user
                WHERE {breaker_sql}
                GROUP BY LOWER(REPLACE(u.uuid, '-', ''))
                ORDER BY NULL
            """
            return sql, tuple(parameters) + breaker_params
        exclusion = (
            f"""NOT EXISTS (
                  SELECT 1 FROM `{self.prefix}block` p
                  STRAIGHT_JOIN `{self.prefix}user` placer ON placer.rowid = p.user
                  WHERE p.wid = b.wid AND p.x = b.x AND p.z = b.z
                    AND p.time <= b.time AND p.y = b.y AND p.type = b.type
                    AND p.action = 1 AND p.rolled_back = 0
                    AND (p.time < b.time OR (p.time = b.time AND p.rowid < b.rowid))
                    AND {placer_sql}
              )"""
            if natural_only
            else ""
        )
        # Production EXPLAIN favors the existing type index over wid for base blocks.
        # Keep the natural-target query's optimizer behavior unchanged.
        index_hint = " FORCE INDEX (`type`)" if not natural_only else ""
        sql = f"""
            SELECT LOWER(REPLACE(u.uuid, '-', '')) AS player_uuid,
                   MIN(u.user) AS player_name,
                   {columns}, COUNT(b.rowid) AS total
            FROM `{self.prefix}block` b{index_hint}
            STRAIGHT_JOIN `{self.prefix}user` u ON u.rowid = b.user
            WHERE {" AND ".join(constraints)}
              AND {breaker_sql}
              {"AND " + exclusion if natural_only else ""}
            GROUP BY LOWER(REPLACE(u.uuid, '-', ''))
            ORDER BY total DESC, player_name ASC, player_uuid ASC
        """
        return sql, tuple(parameters) + breaker_params + (placer_params if natural_only else ())


def get_repository() -> CoreProtectRepository:
    return MariaDBCoreProtectRepository()
