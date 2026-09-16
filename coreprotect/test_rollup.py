from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from .repository import CoreProtectUnavailable
from .test_mining import MiningFixture

MATERIALS = {"stone": "minecraft:stone", "deepslate": "minecraft:deepslate"}


class RollupFixture(MiningFixture):
    stone = 781
    slate = 981

    def setUp(self):
        super().setUp()
        self.db.executemany(
            "INSERT INTO co_material_map VALUES (?, ?)",
            zip(MATERIALS.values(), (self.stone, self.slate), strict=True),
        )

        @contextmanager
        def cursor():
            yield self.cursor

        self.reader_patch = patch.object(self.repository, "_cursor", cursor)
        self.reader_patch.start()
        self.addCleanup(self.reader_patch.stop)


class SyncReaderTests(RollupFixture, SimpleTestCase):
    def test_watermark_captures_all_events_including_irrelevant_materials(self):
        self.assertEqual(self.repository.mining_high_water(), 0)
        self.event(material=999, rowid=50)
        self.assertEqual(self.repository.mining_high_water(), 50)
        batch = self.repository.read_mining_batch(0, 50, 2, MATERIALS)
        self.assertEqual(batch.through_rowid, 50)
        self.assertEqual(batch.buckets, ())

    def test_chunk_gaps_utc_days_worlds_and_normalized_uuid(self):
        self.db.execute(
            "INSERT INTO co_user VALUES (11, 'Previous', ?)",
            ("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",),
        )
        self.event(material=self.stone, time=86399, rowid=2)
        self.event(material=self.stone, time=86399, rowid=10, user=11)
        self.event(material=self.slate, time=86400, rowid=20, wid=999)
        one = self.repository.read_mining_batch(0, 20, 2, MATERIALS)
        self.assertEqual(one.through_rowid, 10)
        self.assertEqual(len(one.buckets), 1)
        self.assertEqual(one.buckets[0].break_count, 2)
        self.assertEqual(one.buckets[0].date, date(1970, 1, 1))
        self.assertEqual(one.buckets[0].player_uuid, "a" * 32)
        two = self.repository.read_mining_batch(10, 20, 2, MATERIALS)
        self.assertEqual(two.buckets[0].date, date(1970, 1, 2))
        self.assertEqual(two.buckets[0].world_id, 999)
        self.assertEqual(two.buckets[0].material_key, "deepslate")

    def test_only_qualifying_breaks_and_dynamic_materials(self):
        self.event(material=self.stone, action=1)
        self.event(material=self.stone, rolled_back=1)
        for actor in (30, 40, 50, 60, 70, 80, 90, 999):
            self.event(material=self.slate, user=actor)
        self.event(material=self.stone)
        self.event(material=self.slate)
        rows = self.repository.read_mining_batch(0, 100, 100, MATERIALS).buckets
        self.assertEqual(
            {r.material_key: r.break_count for r in rows}, {"stone": 1, "deepslate": 1}
        )
        self.db.execute("UPDATE co_material_map SET id = 123 WHERE id = ?", (self.stone,))
        self.event(material=123)
        rows = self.repository.read_mining_batch(0, 100, 100, MATERIALS).buckets
        self.assertEqual({r.material_key: r.break_count for r in rows}["stone"], 1)

    def test_missing_mapping_fails_without_advancing(self):
        self.db.execute("DELETE FROM co_material_map WHERE id = ?", (self.slate,))
        with self.assertRaises(CoreProtectUnavailable):
            self.repository.read_mining_batch(0, 100, 100, MATERIALS)

    def test_reconciliation_obeys_day_and_committed_watermark(self):
        self.event(material=self.stone, time=86400, rowid=1)
        self.event(material=self.stone, time=86401, rowid=2)
        self.event(material=self.stone, time=172800, rowid=3)
        rows = self.repository.read_mining_day(date(1970, 1, 2), 1, MATERIALS)
        self.assertEqual(sum(r.break_count for r in rows), 1)
        self.db.execute("UPDATE co_block SET rolled_back = 1 WHERE rowid = 1")
        self.assertEqual(self.repository.read_mining_day(date(1970, 1, 2), 1, MATERIALS), ())

    def test_sql_bounded_primary_scan_and_reconciliation_type_scan(self):
        self.event(material=self.stone)
        self.repository.read_mining_batch(0, 100, 5, MATERIALS)
        boundary_sql, params = self.cursor.statements[1]
        self.assertIn("rowid > %s AND rowid <= %s", boundary_sql)
        self.assertEqual(params, (0, 100, 5))
        sql, params = self.cursor.statements[2]
        self.assertIn("FORCE INDEX (`PRIMARY`)", sql)
        self.assertIn("FLOOR(b.time / 86400)", sql)
        self.assertIn("u.uuid REGEXP %s", sql)
        self.assertNotIn("NOT EXISTS", sql)
        self.assertNotIn("SELECT *", sql)
        self.assertEqual(params[:2], (0, 100))
        self.repository.read_mining_day(date(1970, 1, 1), 100, MATERIALS)
        sql, params = self.cursor.statements[-1]
        self.assertIn("FORCE INDEX (`type`)", sql)
        self.assertIn("b.time >= %s AND b.time < %s AND b.rowid <= %s", sql)
