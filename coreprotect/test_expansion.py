from django.test import SimpleTestCase

from .mining import ANCIENT_DEBRIS, EMERALD, DiamondQuery
from .test_mining import timestamp
from .test_rollup import RollupFixture


class ExpansionSQLTests(RollupFixture, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.ids = {
            "minecraft:ancient_debris": 2021,
            "minecraft:emerald_ore": 3043,
            "minecraft:deepslate_emerald_ore": 4556,
        }
        self.db.executemany("INSERT INTO co_material_map VALUES (?, ?)", self.ids.items())

    def test_all_new_targets_use_strict_historical_placement_rule(self):
        for group in (ANCIENT_DEBRIS, EMERALD):
            with self.subTest(group=group.slug):
                self.db.execute("DELETE FROM co_block")
                for name in group.target_materials:
                    material = self.ids[name]
                    self.event(material=material, time=1, action=1, x=1)
                    self.event(material=material, time=110, x=1)  # Old placement excluded.
                    self.event(material=material, time=110, x=2)
                    self.event(material=material, time=110, action=1, x=2)  # Later tie allowed.
                    self.event(material=material, time=110, action=1, x=3)
                    self.event(material=material, time=110, x=3)  # Earlier tie excluded.
                    self.event(material=material, time=110, rolled_back=1, x=4)
                    self.event(material=material, time=110, user=30, x=5)
                    self.event(material=material, time=110, wid=999, x=6)
                    self.event(material=material, time=120, x=7)  # Exclusive end excluded.
                    self.event(material=material, time=109, x=8)  # Before start excluded.
                    self.event(material=material, time=1, action=1, rolled_back=1, x=9)
                    self.event(material=material, time=110, x=9)  # Rolled placement allowed.
                rows = self.repository.get_material_stats(
                    DiamondQuery(timestamp(110), timestamp(120), self.world),
                    group.target_materials,
                    natural_only=True,
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].counts, (2,) * len(group.target_materials))
                sql, params = self.cursor.statements[-1]
                self.assertIn("p.time = b.time AND p.rowid < b.rowid", sql)
                self.assertNotIn("p.time >=", sql)
                self.assertNotIn("FORCE INDEX", sql)
                self.assertTrue(all(self.ids[name] in params for name in group.target_materials))

    def test_netherrack_base_keeps_placed_breaks_and_resolves_changed_mapping(self):
        self.db.execute(
            "UPDATE co_material_map SET id=6751 WHERE material=?", ("minecraft:netherrack",)
        )
        self.event(material=6751, time=100, action=1)
        self.event(material=6751, time=101)
        self.event(material=6751, time=102, rolled_back=1)
        self.event(material=6751, time=103, user=30)
        rows = self.repository.get_denominator_stats(DiamondQuery(), ANCIENT_DEBRIS)
        self.assertEqual(rows[0].counts, (1,))
        sql, params = self.cursor.statements[-1]
        self.assertIn("FORCE INDEX (`type`)", sql)
        self.assertNotIn("NOT EXISTS", sql)
        self.assertIn(6751, params)
