"""Execute the repository's real SELECTs on isolated synthetic records.

SQLite supplies relational semantics, not MariaDB execution plans. The cursor shim only
translates parameter markers and STRAIGHT_JOIN, removes the MariaDB index hint, and supplies
MariaDB-style REGEXP matching. Hint placement is asserted separately on the original SQL.
Connection/transaction/timeout behavior is covered separately with the actual driver mocked.
"""

import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .mining import DIAMOND_MATERIALS, DiamondQuery, DiamondStatsRow
from .repository import CoreProtectUnavailable, MariaDBCoreProtectRepository


def timestamp(value):
    return datetime.fromtimestamp(value, UTC)


class SQLiteReadCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if not sql.lstrip().startswith("SELECT"):
            raise AssertionError("Analytics issued a non-SELECT statement.")
        return self.cursor.execute(
            sql.replace("%s", "?")
            .replace("STRAIGHT_JOIN", "JOIN")
            .replace(" FORCE INDEX (`type`)", "")
            .replace(" FORCE INDEX (`PRIMARY`)", ""),
            # PRIMARY is used only by bounded rollup ingestion, not report queries.
            params,
        )

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()


class MiningFixture:
    # These IDs are arbitrary test fixture values, never production mapping constants.
    normal = 7619
    deep = 48027
    world = 83

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.create_function(
            "regexp",
            2,
            lambda pattern, value: bool(
                value is not None and re.search(pattern, value, re.IGNORECASE)
            ),
        )
        self.db.executescript("""
            CREATE TABLE co_material_map (material TEXT, id INTEGER);
            CREATE TABLE co_user (rowid INTEGER PRIMARY KEY, user TEXT, uuid TEXT);
            CREATE TABLE co_block (
                rowid INTEGER PRIMARY KEY, time INTEGER, user INTEGER, wid INTEGER,
                x INTEGER, y INTEGER, z INTEGER, type INTEGER, action INTEGER, rolled_back INTEGER
            );
            CREATE INDEX candidate_index ON co_block(type,time);
            CREATE INDEX location_index ON co_block(wid,x,z,time);
        """)
        self.db.executemany(
            "INSERT INTO co_material_map VALUES (?, ?)",
            zip(DIAMOND_MATERIALS, (self.normal, self.deep), strict=True),
        )
        self.db.executemany(
            "INSERT INTO co_user VALUES (?, ?, ?)",
            [
                (10, "Alice", "a" * 32),
                (20, "Bob", "b" * 32),
                (30, "#water", None),
                (40, "Zombie", None),
                (50, "BadUUID", "not-a-uuid"),
                (60, "#fake", "f" * 32),
                (70, "Nil", "0" * 32),
                (80, "", "e" * 32),
                (90, "NoUUID", ""),
            ],
        )
        self.repository = MariaDBCoreProtectRepository()
        self.cursor = SQLiteReadCursor(self.db)

    def event(
        self,
        *,
        time=100,
        user=10,
        material=None,
        wid=None,
        x=1,
        y=2,
        z=3,
        action=0,
        rolled_back=0,
        rowid=None,
    ):
        cursor = self.db.execute(
            "INSERT INTO co_block VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rowid,
                time,
                user,
                self.world if wid is None else wid,
                x,
                y,
                z,
                self.normal if material is None else material,
                action,
                rolled_back,
            ),
        )
        return cursor.lastrowid

    def stats(self, query=None):
        @contextmanager
        def read_cursor():
            yield self.cursor

        with patch.object(self.repository, "_cursor", read_cursor):
            return self.repository.get_diamond_stats(query or DiamondQuery())


class NaturalMiningTests(MiningFixture, SimpleTestCase):
    def test_natural_diamond_break(self):
        self.event()
        self.assertEqual(self.stats(), (DiamondStatsRow("a" * 32, "Alice", 1, 0),))

    def test_natural_deepslate_break(self):
        self.event(material=self.deep)
        self.assertEqual(self.stats()[0].deepslate_diamond_ore, 1)
        self.assertEqual(self.stats()[0].diamond_ore, 0)

    def test_rolled_back_break_and_non_break_actions_do_not_count(self):
        self.event(rolled_back=1)
        for action in (1, 2, 3):
            self.event(action=action)
        self.assertEqual(self.stats(), ())

    def test_earlier_player_placement_excludes_even_if_another_player_placed(self):
        self.event(time=50, user=20, action=1)
        self.event()
        self.assertEqual(self.stats(), ())

    def test_later_placement_does_not_invalidate_natural_break(self):
        self.event(time=50)
        self.event(action=1)
        self.assertEqual(self.stats()[0].total, 1)

    def test_placement_before_reporting_window_still_excludes(self):
        self.event(time=10, action=1)
        self.event(time=100)
        self.assertEqual(self.stats(DiamondQuery(timestamp(90), timestamp(110))), ())

    def test_same_second_lower_rowid_placement_excludes(self):
        self.event(action=1, rowid=500)
        self.event(rowid=501)
        self.assertEqual(self.stats(), ())

    def test_same_second_higher_rowid_placement_does_not_exclude(self):
        self.event(rowid=500)
        self.event(action=1, rowid=501)
        self.assertEqual(self.stats()[0].total, 1)

    def test_time_takes_precedence_over_rowid(self):
        self.event(time=50, rowid=501, action=1)
        self.event(time=100, rowid=500)
        self.assertEqual(self.stats(), ())

    def test_other_material_placement_does_not_exclude(self):
        self.event(time=50, action=1, material=self.deep)
        self.event()
        self.assertEqual(self.stats()[0].total, 1)

    def test_each_coordinate_and_world_must_match(self):
        for different in ({"x": 9}, {"y": 9}, {"z": 9}, {"wid": 999}):
            with self.subTest(different=different):
                self.db.execute("DELETE FROM co_block")
                self.event(time=50, action=1, **different)
                self.event()
                self.assertEqual(self.stats()[0].total, 1)

    def test_rolled_back_placement_does_not_exclude(self):
        self.event(time=50, action=1, rolled_back=1)
        self.event()
        self.assertEqual(self.stats()[0].total, 1)

    def test_silk_touch_then_fortune_counts_only_original_discovery(self):
        self.event(time=10)
        self.event(time=20, x=50, action=1)
        self.event(time=30, x=50)
        self.assertEqual(self.stats()[0].total, 1)

    def test_pseudo_users_and_missing_mappings_never_appear(self):
        for user in (30, 40, 50, 60, 70, 80, 90, 999):
            self.event(user=user)
        self.assertEqual(self.stats(), ())

    def test_non_player_placements_do_not_invalidate_breaks(self):
        for user in (30, 40, 50, 60, 70, 80, 90, 999):
            self.event(time=50, action=1, user=user)
        self.event()
        self.assertEqual(self.stats()[0].total, 1)

    def test_both_materials_aggregate_and_total_orders_before_name(self):
        self.event(user=10)
        self.event(user=20)
        self.event(user=20, material=self.deep)
        rows = self.stats()
        self.assertEqual([row.player_name for row in rows], ["Bob", "Alice"])
        self.assertEqual(
            (rows[0].diamond_ore, rows[0].deepslate_diamond_ore, rows[0].total), (1, 1, 2)
        )

    def test_ties_order_by_name_then_uuid(self):
        self.db.execute("INSERT INTO co_user VALUES (21, 'Bob', ?)", ("c" * 32,))
        for user in (21, 20, 10):
            self.event(user=user)
        rows = self.stats()
        self.assertEqual(
            [(r.player_name, r.player_uuid) for r in rows],
            [
                ("Alice", "a" * 32),
                ("Bob", "b" * 32),
                ("Bob", "c" * 32),
            ],
        )

    def test_duplicate_uuid_records_aggregate_as_one_player(self):
        self.db.execute(
            "INSERT INTO co_user VALUES (11, 'Zprevious', ?)",
            ("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",),
        )
        self.event(user=10)
        self.event(user=11, material=self.deep)
        self.assertEqual(self.stats(), (DiamondStatsRow("a" * 32, "Alice", 1, 1),))

    def test_time_bounds_inclusive_start_exclusive_end(self):
        for time in (89, 90, 99, 100):
            self.event(time=time)
        self.assertEqual(self.stats(DiamondQuery(timestamp(90), timestamp(100)))[0].total, 2)

    def test_subsecond_bounds_match_integer_event_times(self):
        for time in (90, 91, 100, 101):
            self.event(time=time)
        self.assertEqual(self.stats(DiamondQuery(timestamp(90.5), timestamp(100.5)))[0].total, 2)

    def test_world_filter_only_counts_selected_breaks(self):
        self.event()
        self.event(wid=900)
        self.assertEqual(self.stats(DiamondQuery(world_id=900))[0].total, 1)

    def test_all_time_has_no_fixed_start_or_now_cutoff(self):
        self.event(time=1)
        self.event(time=2_000_000_000)
        self.assertEqual(self.stats()[0].total, 2)

    def test_only_diamonds_count_and_material_ids_are_resolved_on_each_uncached_query(self):
        self.event(material=123)
        self.assertEqual(self.stats(), ())
        self.db.execute(
            "UPDATE co_material_map SET id = 123 WHERE material = ?", (DIAMOND_MATERIALS[0],)
        )
        self.assertEqual(self.stats()[0].diamond_ore, 1)

    def test_missing_or_ambiguous_materials_fail_instead_of_reporting_partial_counts(self):
        self.event()
        self.db.execute("DELETE FROM co_material_map WHERE material = ?", (DIAMOND_MATERIALS[1],))
        with self.assertRaises(CoreProtectUnavailable):
            self.stats()
        self.db.execute(
            "INSERT INTO co_material_map VALUES (?, ?)", (DIAMOND_MATERIALS[1], self.normal)
        )
        with self.assertRaises(CoreProtectUnavailable):
            self.stats()

    def test_fixed_query_count_and_sql_contract(self):
        self.event()
        self.stats(DiamondQuery(timestamp(10), timestamp(110), self.world))
        self.assertEqual(len(self.cursor.statements), 2)
        mapping_sql, names = self.cursor.statements[0]
        self.assertEqual(names, DIAMOND_MATERIALS)
        self.assertNotIn(DIAMOND_MATERIALS[0], mapping_sql)
        sql, params = self.cursor.statements[1]
        for clause in (
            "b.type IN (%s, %s)",
            "b.action = 0",
            "b.rolled_back = 0",
            "b.time >= %s",
            "b.time < %s",
            "b.wid = %s",
            "NOT EXISTS",
            "p.wid = b.wid",
            "p.x = b.x",
            "p.y = b.y",
            "p.z = b.z",
            "p.type = b.type",
            "p.action = 1",
            "p.rolled_back = 0",
            "p.time < b.time OR (p.time = b.time AND p.rowid < b.rowid)",
            "placer.rowid = p.user",
            "placer.uuid REGEXP %s",
            "u.uuid REGEXP %s",
            "ORDER BY total DESC, player_name ASC, player_uuid ASC",
        ):
            self.assertIn(clause, sql)
        self.assertNotIn("p.time >=", sql)
        self.assertNotIn("SELECT *", sql)
        self.assertNotIn("blob", sql.lower())
        self.assertEqual(
            params[:7], (self.normal, self.deep, self.normal, self.deep, 10, 110, self.world)
        )


@override_settings(
    COREPROTECT_DB_NAME="fixture",
    COREPROTECT_DB_USER="reader",
    COREPROTECT_DB_PASSWORD="fixture-secret",
)
class MiningDriverTests(SimpleTestCase):
    @patch("coreprotect.repository.pymysql.connect")
    def test_analytics_preserves_read_only_session_and_timeouts(self, connect):
        connection = connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [list(zip(DIAMOND_MATERIALS, (99, 771), strict=True)), []]
        self.assertEqual(MariaDBCoreProtectRepository().get_diamond_stats(DiamondQuery()), ())
        cursor.execute.assert_any_call("START TRANSACTION READ ONLY")
        cursor.execute.assert_any_call("SET SESSION max_statement_time = %s", (3,))
        self.assertEqual(connect.call_args.kwargs["read_timeout"], 3)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    @override_settings(COREPROTECT_TABLE_PREFIX="other_")
    @patch("coreprotect.repository.pymysql.connect")
    def test_custom_prefix_is_used_in_all_tables(self, connect):
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [list(zip(DIAMOND_MATERIALS, (99, 771), strict=True)), []]
        MariaDBCoreProtectRepository().get_diamond_stats(DiamondQuery())
        sql = cursor.execute.call_args.args[0]
        self.assertIn("`other_block`", sql)
        self.assertIn("`other_user`", sql)
        self.assertNotIn("`co_", sql)
