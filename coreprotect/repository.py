"""CoreProtect is external and read-only. Never register it in Django DATABASES."""

import re
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Protocol

import pymysql
from django.conf import settings


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


def get_repository() -> CoreProtectRepository:
    return MariaDBCoreProtectRepository()
