from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from coreprotect.mining import DIAMONDS, DiamondQuery, DiamondStatsRow, MaterialBreakRow

from . import rollup_config as config
from .forms import DiamondFiltersForm
from .models import MiningAnalyticsSyncState, MiningMaterialDaily
from .rollups import RollupUnavailable, denominators, read_snapshot, split_range
from .services import get_report, layer_rows
from .sync import material_signature

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def ready_state(now=None):
    return MiningAnalyticsSyncState.objects.create(
        source_name=config.SOURCE_NAME,
        initialized=True,
        last_success_at=now or timezone.now(),
        last_reconciled_at=now or timezone.now(),
        material_signature=material_signature(),
        generation=1,
    )


class SplittingTests(SimpleTestCase):
    def test_all_time_never_has_live_boundary(self):
        parts = split_range(DiamondQuery())
        self.assertIsNone(parts.start_date)
        self.assertIsNone(parts.end_date)
        self.assertEqual(parts.boundaries, ())

    def test_whole_days_and_precise_multi_day_range(self):
        start = datetime(2026, 9, 1, tzinfo=UTC)
        end = datetime(2026, 9, 10, tzinfo=UTC)
        whole = split_range(DiamondQuery(start, end, 987))
        self.assertEqual((whole.start_date, whole.end_date), (date(2026, 9, 1), date(2026, 9, 10)))
        self.assertEqual(whole.boundaries, ())
        query = DiamondQuery(
            start + timedelta(hours=14, minutes=30), end + timedelta(hours=18, minutes=15), 987
        )
        parts = split_range(query)
        self.assertEqual((parts.start_date, parts.end_date), (date(2026, 9, 2), date(2026, 9, 10)))
        self.assertEqual(
            parts.boundaries,
            (
                DiamondQuery(query.start, start + timedelta(days=1), 987),
                DiamondQuery(end, query.end, 987),
            ),
        )

    def test_quick_ranges_and_same_day_preserve_exact_coverage(self):
        for days in (1, 7, 30):
            query = DiamondQuery(NOW - timedelta(days=days), NOW)
            parts = split_range(query)
            self.assertEqual(len(parts.boundaries), 2)
            span = sum((b.end - b.start for b in parts.boundaries), timedelta())
            span += timedelta(days=(parts.end_date - parts.start_date).days)
            self.assertEqual(span, timedelta(days=days))
        query = DiamondQuery(NOW, NOW + timedelta(microseconds=1))
        self.assertEqual(split_range(query).boundaries, (query,))

    def test_midnight_end_and_no_overlapping_days(self):
        midnight = NOW.replace(hour=0)
        for start, end in (
            (midnight, NOW),
            (NOW, midnight + timedelta(days=1)),
            (NOW, midnight + timedelta(days=1, microseconds=1)),
        ):
            parts = split_range(DiamondQuery(start, end))
            self.assertTrue(all(b.end - b.start < timedelta(days=1) for b in parts.boundaries))
            if len(parts.boundaries) == 2:
                self.assertLessEqual(parts.boundaries[0].end, parts.boundaries[1].start)


class ReportRollupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def bucket(self, day, count, *, material="stone", world=83, uuid="a" * 32):
        return MiningMaterialDaily.objects.create(
            date=day, player_uuid=uuid, world_id=world, material_key=material, break_count=count
        )

    def test_bootstrap_never_calls_coreprotect_denominator_or_target(self):
        with patch("analytics.services.get_repository") as factory:
            with self.assertRaises(RollupUnavailable):
                get_report(DiamondFiltersForm({}, worlds=()))
            factory.assert_not_called()
        state = ready_state(NOW)
        state.initialized = False
        state.save()
        self.bucket(NOW.date(), 999)
        with self.assertRaises(RollupUnavailable):
            read_snapshot(DiamondQuery(), NOW)

    def test_all_time_postgres_world_material_and_uuid_merge(self):
        ready_state(NOW)
        self.bucket(date(1970, 1, 1), 50)
        self.bucket(date(2026, 9, 15), 150)
        self.bucket(date(2026, 9, 15), 300, material="deepslate")
        self.bucket(date(2026, 9, 15), 900, world=999)
        snapshot = read_snapshot(DiamondQuery(world_id=83), NOW)
        repo = Mock()
        self.assertEqual(
            denominators(snapshot, repo), (MaterialBreakRow("a" * 32, "", (200, 300)),)
        )
        repo.get_denominator_stats.assert_not_called()

    def test_hybrid_only_reads_complete_days_from_postgres(self):
        ready_state(NOW)
        for day in (1, 2, 3):
            self.bucket(date(2026, 9, day), 100)
        query = DiamondQuery(
            datetime(2026, 9, 1, 14, tzinfo=UTC), datetime(2026, 9, 3, 18, tzinfo=UTC)
        )
        snapshot = read_snapshot(query, NOW)
        self.assertEqual(snapshot.counts[0].counts, (100, 0))
        repo = Mock()
        repo.get_denominator_stats.return_value = (MaterialBreakRow("a" * 32, "Alice", (10, 0)),)
        rows = denominators(snapshot, repo)
        self.assertEqual(sum(row.counts[0] for row in rows), 120)
        self.assertEqual(repo.get_denominator_stats.call_count, 2)
        for call, boundary in zip(
            repo.get_denominator_stats.call_args_list, snapshot.boundaries, strict=True
        ):
            self.assertEqual(call.args, (boundary, DIAMONDS))

    def test_fresh_warning_expired_and_failed_sync_states(self):
        state = ready_state(NOW)
        self.assertFalse(read_snapshot(DiamondQuery(), NOW).warning)
        self.assertTrue(read_snapshot(DiamondQuery(), NOW + timedelta(minutes=16)).warning)
        with self.assertRaises(RollupUnavailable):
            read_snapshot(DiamondQuery(), NOW + timedelta(hours=25))
        state.last_error = "Fixed safe failure"
        state.save()
        self.assertTrue(read_snapshot(DiamondQuery(), NOW).warning)
        state.material_signature = "old"
        state.save()
        with self.assertRaises(RollupUnavailable):
            read_snapshot(DiamondQuery(), NOW)

    def test_sync_generation_changes_cached_report(self):
        state = ready_state()
        self.bucket(date(2026, 9, 1), 100)
        with patch("analytics.services.get_repository") as factory:
            repo = factory.return_value
            repo.get_diamond_stats.return_value = (DiamondStatsRow("a" * 32, "Alice", 2, 3),)
            form = DiamondFiltersForm({}, worlds=())
            first = get_report(form)
            self.assertEqual(get_report(form), first)
            MiningMaterialDaily.objects.update(break_count=200)
            state.generation += 1
            state.save()
            second = get_report(form)
            self.assertEqual(first.rows[0].stone, 100)
            self.assertEqual(second.rows[0].stone, 200)
            self.assertEqual(repo.get_diamond_stats.call_count, 2)
            repo.get_denominator_stats.assert_not_called()

    def test_separate_layers_sort_filter_and_small_samples(self):
        rows = (
            DiamondStatsRow("a" * 32, "Alice", 2, 0, 999, 4000),
            DiamondStatsRow("b" * 32, "Bob", 0, 10, 4000, 999),
            DiamondStatsRow("c" * 32, "Carol", 5, 1, 1000, 1000),
        )
        normal = layer_rows(rows, "diamond_ore", "stone")
        deep = layer_rows(rows, "deepslate_diamond_ore", "deepslate")
        self.assertEqual([r.player_name for r in normal], ["Carol", "Alice"])
        self.assertEqual([r.player_name for r in deep], ["Carol", "Bob"])
        self.assertFalse(normal[0].small_sample)
        self.assertTrue(normal[1].small_sample)
        self.assertFalse(deep[0].small_sample)
        self.assertTrue(deep[1].small_sample)
        self.assertEqual(normal[0].per_1000, 5)
        self.assertEqual(normal[0].per_target, 200)
        self.assertEqual(deep[0].per_1000, 1)
        self.assertEqual(deep[0].per_target, 1000)
        zero = layer_rows((DiamondStatsRow("a" * 32, "Alice", 1, 1),), "diamond_ore", "stone")[0]
        self.assertIsNone(zero.per_1000)
        self.assertEqual(zero.per_target, 0)
