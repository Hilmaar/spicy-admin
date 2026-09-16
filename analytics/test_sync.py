from datetime import UTC, date, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase

from coreprotect.repository import CoreProtectUnavailable
from coreprotect.test_rollup import RollupFixture

from . import rollup_config as config
from .models import MiningAnalyticsSyncState, MiningMaterialDaily
from .sync import SyncBusy, SyncNeedsRebuild, reconciliation_dates, sync_lock, sync_mining

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


class SyncTests(RollupFixture, TestCase):
    def setUp(self):
        super().setUp()
        factory = patch("analytics.sync.get_repository", return_value=self.repository)
        factory.start()
        self.addCleanup(factory.stop)
        clock = patch("analytics.sync.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def state(self):
        return MiningAnalyticsSyncState.objects.get(pk=config.SOURCE_NAME)

    def total(self):
        return sum(MiningMaterialDaily.objects.values_list("break_count", flat=True))

    def test_backfill_then_incremental_restart_idempotent(self):
        self.event(material=self.stone, rowid=10)
        self.event(material=self.slate, rowid=20, wid=999)
        sync_mining(batch_size=1)
        self.assertEqual(self.state().last_processed_rowid, 20)
        self.assertTrue(self.state().initialized)
        self.assertEqual(self.total(), 2)
        self.assertEqual(
            set(MiningMaterialDaily.objects.values_list("material_key", flat=True)),
            {"stone", "deepslate"},
        )
        self.event(material=self.stone, rowid=30)
        with patch.object(
            self.repository, "read_mining_batch", wraps=self.repository.read_mining_batch
        ) as read:
            sync_mining(batch_size=1)
            self.assertEqual(read.call_args.args[:2], (20, 30))
        sync_mining()
        self.assertEqual(self.total(), 3)

    def test_failed_batch_commit_rolls_back_counts_and_watermark(self):
        self.event(material=self.stone)
        original = MiningAnalyticsSyncState.save

        def fail_after_counts(state, *args, **kwargs):
            if state.last_processed_rowid:
                raise IntegrityError("synthetic secret")
            return original(state, *args, **kwargs)

        with (
            patch.object(MiningAnalyticsSyncState, "save", fail_after_counts),
            self.assertRaises(IntegrityError),
        ):
            sync_mining()
        self.assertEqual(self.total(), 0)
        self.assertEqual(self.state().last_processed_rowid, 0)
        self.assertNotIn("secret", self.state().last_error)
        sync_mining()
        self.assertEqual(self.total(), 1)

    def test_partial_backfill_resumes_captured_target_without_duplicates(self):
        for rowid in (1, 2, 3):
            self.event(material=self.stone, rowid=rowid)
        read = self.repository.read_mining_batch

        def interrupted(after, *args):
            if after == 1:
                raise CoreProtectUnavailable("secret")
            return read(after, *args)

        with (
            patch.object(self.repository, "read_mining_batch", side_effect=interrupted),
            self.assertRaises(CoreProtectUnavailable),
        ):
            sync_mining(batch_size=1)
        self.assertEqual(self.total(), 1)
        self.assertFalse(self.state().initialized)
        self.event(material=self.stone, rowid=4)
        sync_mining(batch_size=1)
        self.assertEqual(self.total(), 3)
        self.assertEqual(self.state().last_processed_rowid, 3)
        sync_mining()
        self.assertEqual(self.total(), 4)

    def test_recent_rollbacks_replaced_old_buckets_preserved(self):
        self.event(material=self.stone, time=int(NOW.timestamp()) - 3600, rowid=1)
        self.event(material=self.slate, time=100, rowid=2)
        sync_mining()
        self.assertEqual(self.total(), 2)
        self.db.execute("UPDATE co_block SET rolled_back = 1")
        sync_mining()
        self.assertEqual(self.total(), 1)
        self.assertEqual(MiningMaterialDaily.objects.get().date, date(1970, 1, 1))
        sync_mining(full_rebuild=True)
        self.assertEqual(self.total(), 0)

    def test_source_shrink_during_backfill_requires_review(self):
        self.event(material=self.stone, rowid=10)
        with (
            patch.object(
                self.repository, "read_mining_batch", side_effect=CoreProtectUnavailable()
            ),
            self.assertRaises(CoreProtectUnavailable),
        ):
            sync_mining()
        self.db.execute("DELETE FROM co_block")
        with self.assertRaises(SyncNeedsRebuild):
            sync_mining()
        self.assertFalse(self.state().initialized)
        self.assertEqual(self.state().last_processed_rowid, 0)

    def test_reconciliation_is_atomic_and_does_not_include_future_incremental_rows(self):
        self.event(material=self.stone, time=int(NOW.timestamp()), rowid=1)
        sync_mining()
        previous = self.state().last_reconciled_at
        self.db.execute("UPDATE co_block SET rolled_back = 1 WHERE rowid = 1")
        with (
            patch.object(
                MiningMaterialDaily.objects, "bulk_create", side_effect=IntegrityError("fail")
            ),
            self.assertRaises(IntegrityError),
        ):
            sync_mining(reconcile_only=True)
        self.assertEqual(self.total(), 1)
        self.assertEqual(self.state().last_reconciled_at, previous)
        self.event(material=self.stone, time=int(NOW.timestamp()), rowid=2)
        sync_mining(reconcile_only=True)
        self.assertEqual(self.total(), 0)
        self.assertEqual(self.state().last_processed_rowid, 1)
        sync_mining()
        self.assertEqual(self.total(), 1)
        sync_mining()
        self.assertEqual(self.total(), 1)

    def test_reconciliation_failure_never_exposes_partial_day_replacement(self):
        self.event(material=self.stone, time=int(NOW.timestamp()))
        sync_mining()
        with (
            patch.object(
                self.repository, "read_mining_day", side_effect=CoreProtectUnavailable("secret")
            ),
            self.assertRaises(CoreProtectUnavailable),
        ):
            sync_mining(reconcile_only=True)
        self.assertEqual(self.total(), 1)

    def test_reconcile_only_does_not_refresh_forward_freshness(self):
        sync_mining()
        previous = self.state().last_success_at
        with patch("analytics.sync.timezone.now", return_value=NOW + timedelta(hours=1)):
            sync_mining(reconcile_only=True)
        self.assertEqual(self.state().last_success_at, previous)

    def test_day_window_is_configurable_and_expands_to_full_utc_dates(self):
        self.assertEqual(
            reconciliation_dates(NOW, 48), (date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16))
        )
        self.assertEqual(reconciliation_dates(NOW, 1), (date(2026, 9, 16),))
        with patch.object(
            self.repository, "read_mining_day", wraps=self.repository.read_mining_day
        ) as read:
            sync_mining(reconcile_hours=1)
            self.assertEqual(read.call_count, 1)

    def test_model_identity_uniqueness_and_separation(self):
        values = dict(
            date=date(2026, 9, 1),
            player_uuid="a" * 32,
            world_id=83,
            material_key="stone",
            break_count=1,
        )
        MiningMaterialDaily.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MiningMaterialDaily.objects.create(**values)
        for changes in (
            {"date": date(2026, 9, 2)},
            {"player_uuid": "b" * 32},
            {"world_id": 99},
            {"material_key": "deepslate"},
        ):
            MiningMaterialDaily.objects.create(**(values | changes))
        self.assertEqual(MiningMaterialDaily.objects.count(), 5)

    def test_overlap_exits_safely_and_lock_releases_on_failure(self):
        with sync_lock(), self.assertRaises(SyncBusy):
            sync_mining()
        sync_mining()
        output = StringIO()
        with sync_lock():
            call_command("sync_mining_analytics", stdout=output)
        self.assertIn("Another mining analytics sync", output.getvalue())

    def test_postgres_advisory_lock_contract(self):
        with patch("analytics.sync.connection") as connection:
            connection.vendor = "postgresql"
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = (False,)
            with self.assertRaises(SyncBusy), sync_lock():
                pass
            self.assertEqual(cursor.execute.call_count, 1)
            cursor.fetchone.return_value = (True,)
            with self.assertRaises(RuntimeError), sync_lock():
                raise RuntimeError("interrupted")
            cursor.execute.assert_called_with("SELECT pg_advisory_unlock(%s)", [config.LOCK_ID])

    def test_config_change_requires_full_rebuild_and_command_errors_are_generic(self):
        sync_mining()
        with (
            patch.dict(config.ROLLUP_MATERIALS, {"fixture": "minecraft:fixture"}),
            self.assertRaises(SyncNeedsRebuild),
        ):
            sync_mining()
        with (
            patch.object(
                self.repository,
                "mining_high_water",
                side_effect=CoreProtectUnavailable("password=secret"),
            ),
            self.assertRaises(CommandError) as caught,
        ):
            call_command("sync_mining_analytics", stdout=StringIO())
        self.assertNotIn("secret", str(caught.exception))
