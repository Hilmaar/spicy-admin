from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from .mining import DIAMONDS, DiamondQuery, MaterialBreakRow, OreGroup
from .repository import CoreProtectUnavailable
from .test_mining import MiningFixture, timestamp


class DenominatorTests(MiningFixture, SimpleTestCase):
    stone = 9812
    slate = 7183

    def setUp(self):
        super().setUp()
        self.db.executemany(
            "INSERT INTO co_material_map VALUES (?, ?)",
            zip(DIAMONDS.denominator_materials, (self.stone, self.slate), strict=True),
        )

    def bases(self, query=None, group=DIAMONDS):
        @contextmanager
        def cursor():
            yield self.cursor

        with patch.object(self.repository, "_cursor", cursor):
            return self.repository.get_denominator_stats(query or DiamondQuery(), group)

    def test_stone_and_deepslate_counts_split_by_player(self):
        self.event(material=self.stone)
        self.event(material=self.slate)
        self.event(material=self.slate, user=20)
        self.assertEqual(
            self.bases(),
            (
                MaterialBreakRow("a" * 32, "Alice", (1, 1)),
                MaterialBreakRow("b" * 32, "Bob", (0, 1)),
            ),
        )

    def test_rolled_back_and_non_break_actions_excluded(self):
        for material in (self.stone, self.slate):
            self.event(material=material, rolled_back=1)
            for action in (1, 2, 3):
                self.event(material=material, action=action)
        self.assertEqual(self.bases(), ())

    def test_pseudo_missing_and_invalid_player_records_excluded(self):
        for user in (30, 40, 50, 60, 70, 80, 90, 999):
            self.event(material=self.stone, user=user)
        self.assertEqual(self.bases(), ())

    def test_placed_base_breaks_count_but_placed_diamonds_stay_excluded(self):
        for material in (self.stone, self.slate, self.normal, self.deep):
            self.event(material=material, time=1, action=1)
            self.event(material=material, time=100)
        query = DiamondQuery(timestamp(90), timestamp(110))
        self.assertEqual(self.bases(query)[0].counts, (1, 1))
        self.assertEqual(self.stats(query), ())

    def test_time_and_world_bounds_apply_to_breaks(self):
        for time in (89, 90, 99, 100):
            for wid in (self.world, 999):
                self.event(material=self.stone, time=time, wid=wid)
        self.assertEqual(
            self.bases(DiamondQuery(timestamp(90), timestamp(100), self.world))[0].counts, (2, 0)
        )

    def test_whole_day_end_includes_last_second_and_excludes_next_midnight(self):
        for time in (0, 86400 - 1, 86400):
            self.event(material=self.stone, time=time)
        self.assertEqual(self.bases(DiamondQuery(timestamp(0), timestamp(86400)))[0].counts, (2, 0))

    def test_precise_subsecond_bounds(self):
        for time in (10, 11, 20, 21):
            self.event(material=self.slate, time=time)
        self.assertEqual(
            self.bases(DiamondQuery(timestamp(10.5), timestamp(20.5)))[0].counts, (0, 2)
        )

    def test_material_ids_are_resolved_dynamically(self):
        self.event(material=345)
        self.assertEqual(self.bases(), ())
        self.db.execute(
            "UPDATE co_material_map SET id = 345 WHERE material = ?",
            (DIAMONDS.denominator_materials[0],),
        )
        self.assertEqual(self.bases()[0].counts, (1, 0))

    def test_missing_and_ambiguous_mapping_fail_safely(self):
        self.db.execute("DELETE FROM co_material_map WHERE id = ?", (self.slate,))
        with self.assertRaises(CoreProtectUnavailable):
            self.bases()
        self.db.execute(
            "INSERT INTO co_material_map VALUES (?, ?)",
            (DIAMONDS.denominator_materials[1], self.stone),
        )
        with self.assertRaises(CoreProtectUnavailable):
            self.bases()

    def test_duplicate_uuid_grouping(self):
        self.db.execute(
            "INSERT INTO co_user VALUES (11, 'PreviousName', ?)",
            ("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",),
        )
        self.event(material=self.stone)
        self.event(material=self.slate, user=11)
        self.assertEqual(self.bases(), (MaterialBreakRow("a" * 32, "Alice", (1, 1)),))

    def test_bounded_queries_without_placement_lookup_or_truncation(self):
        self.bases(DiamondQuery(timestamp(90), timestamp(110), self.world))
        self.assertEqual(len(self.cursor.statements), 2)
        mapping, names = self.cursor.statements[0]
        self.assertEqual(names, DIAMONDS.denominator_materials)
        self.assertNotIn(names[0], mapping)
        sql, params = self.cursor.statements[1]
        for fragment in ("NOT EXISTS", "placer", "SELECT *", "LIMIT", "blob"):
            self.assertNotIn(fragment, sql)
        for fragment in ("b.action = 0", "b.rolled_back = 0", "u.uuid REGEXP %s"):
            self.assertIn(fragment, sql)
        self.assertEqual(
            params[:7], (self.stone, self.slate, self.stone, self.slate, 90, 110, self.world)
        )

    def test_one_material_group_reuses_aggregate_without_extra_page(self):
        group = OreGroup("fixture", ("minecraft:diamond_ore",), ("minecraft:stone",))
        self.event(material=self.stone)
        self.event(material=self.slate)
        self.assertEqual(self.bases(group=group)[0].counts, (1,))

    def test_only_denominator_queries_force_existing_type_index(self):
        for query in (DiamondQuery(), DiamondQuery(timestamp(10), timestamp(100), self.world)):
            with self.subTest(query=query):
                sql, _ = self.repository._aggregate_statement(
                    query, (self.stone, self.slate), natural_only=False
                )
                self.assertIn("FROM `co_block` b FORCE INDEX (`type`)", sql)
                self.assertEqual(sql.count("FORCE INDEX"), 1)
                self.assertNotIn("NOT EXISTS", sql)
                target_sql, _ = self.repository._diamond_statement(query, self.normal, self.deep)
                self.assertNotIn("FORCE INDEX", target_sql)
                self.assertIn("NOT EXISTS", target_sql)
