from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase

from accounts.discord import Membership
from accounts.models import User
from coreprotect.mining import DIAMONDS, SMALL_SAMPLE_BASE_BLOCKS, DiamondStatsRow, MaterialBreakRow
from coreprotect.repository import CoreProtectUnavailable, World

from .forms import DiamondFiltersForm
from .models import MiningAnalyticsSyncState, MiningMaterialDaily
from .rollups import RollupUnavailable
from .services import get_report, merge_diamond_rows
from .templatetags.mining import mining_ratio
from .test_rollups import ready_state


class RatioTests(TestCase):
    def test_only_target_players_with_normalized_denominator_merge(self):
        rows = merge_diamond_rows(
            (DiamondStatsRow("a" * 32, "Alice", 2, 3), DiamondStatsRow("b" * 32, "Bob", 1, 0)),
            (
                MaterialBreakRow("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", "Zold", (100, 200)),
                MaterialBreakRow("c" * 32, "Carol", (10, 20)),
            ),
        )
        self.assertEqual(
            rows,
            (
                DiamondStatsRow("a" * 32, "Alice", 2, 3, 100, 200),
                DiamondStatsRow("b" * 32, "Bob", 1, 0, 0, 0),
            ),
        )

    def test_all_ratio_formulas(self):
        row = DiamondStatsRow("a" * 32, "Alice", 2, 3, 100, 300)
        self.assertEqual((row.total, row.total_base_blocks), (5, 400))
        self.assertEqual(row.diamonds_per_1000, Decimal("12.5"))
        self.assertEqual(row.base_blocks_per_diamond, 80)
        self.assertEqual(row.stone_per_normal_diamond, 50)
        self.assertEqual(row.deepslate_per_deep_diamond, 100)

    def test_zero_target_totals_never_create_visible_rows(self):
        self.assertEqual(
            merge_diamond_rows(
                (DiamondStatsRow("a" * 32, "Alice", 0, 0),),
                (MaterialBreakRow("a" * 32, "Alice", (100, 200)),),
            ),
            (),
        )

    def test_zero_divisors_and_actual_zero_ratios(self):
        target_only = DiamondStatsRow("a" * 32, "Alice", 1, 0)
        base_only = DiamondStatsRow("b" * 32, "Bob", 0, 0, 2000, 0)
        self.assertEqual(mining_ratio(target_only.diamonds_per_1000), "—")
        self.assertEqual(mining_ratio(target_only.base_blocks_per_diamond), "0.00")
        self.assertEqual(mining_ratio(base_only.diamonds_per_1000), "0.00")
        self.assertEqual(mining_ratio(base_only.base_blocks_per_diamond), "—")
        self.assertEqual(mining_ratio(target_only.deepslate_per_deep_diamond), "—")
        self.assertEqual(mining_ratio(Decimal("1234.567")), "1,234.57")

    def test_small_sample_boundary_does_not_change_counts(self):
        for count, expected in (
            (0, True),
            (SMALL_SAMPLE_BASE_BLOCKS - 1, True),
            (SMALL_SAMPLE_BASE_BLOCKS, False),
        ):
            row = DiamondStatsRow("a" * 32, "Alice", 1, 0, count, 0)
            self.assertEqual(row.small_sample, expected)
            self.assertEqual(row.stone, count)

    def test_ties_order_by_name_then_uuid_for_target_players(self):
        rows = merge_diamond_rows(
            (
                DiamondStatsRow("c" * 32, "Bob", 1, 0),
                DiamondStatsRow("b" * 32, "Bob", 0, 1),
                DiamondStatsRow("a" * 32, "Alice", 1, 0),
            ),
            (
                MaterialBreakRow("c" * 32, "Bob", (200, 0)),
                MaterialBreakRow("b" * 32, "Bob", (100, 0)),
                MaterialBreakRow("a" * 32, "Alice", (1, 0)),
            ),
        )
        self.assertEqual([r.player_uuid for r in rows], ["a" * 32, "b" * 32, "c" * 32])

    @patch("analytics.services.get_repository")
    def test_same_bounds_and_atomic_success_cache(self, factory):
        cache.clear()
        self.addCleanup(cache.clear)
        ready_state()
        repo = factory.return_value
        repo.get_diamond_stats.return_value = (DiamondStatsRow("a" * 32, "Alice", 1, 0),)
        repo.get_denominator_stats.side_effect = CoreProtectUnavailable("secret")
        form = DiamondFiltersForm(
            {"range": "custom", "start": "2026-09-01T12:00", "end": "2026-09-01T12:30"}, worlds=()
        )
        with patch("analytics.services.cache.set") as store:
            with self.assertRaises(CoreProtectUnavailable):
                get_report(form)
            store.assert_not_called()
        query = repo.get_diamond_stats.call_args.args[0]
        repo.get_denominator_stats.assert_called_once_with(query, DIAMONDS)
        repo.get_denominator_stats.side_effect = None
        repo.get_denominator_stats.return_value = (MaterialBreakRow("a" * 32, "Alice", (10, 20)),)
        first = get_report(form)
        self.assertEqual(get_report(form), first)
        self.assertEqual(first.rows[0].total_base_blocks, 30)
        self.assertEqual(repo.get_denominator_stats.call_count, 2)


class RatioPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        ready_state()
        user = User.objects.create_user("991", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        roles = patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))
        )
        roles.start()
        self.addCleanup(roles.stop)
        factory = patch("analytics.services.get_repository")
        self.repo = factory.start().return_value
        self.addCleanup(factory.stop)
        self.repo.list_worlds.return_value = (World(87, "fixture"),)
        self.repo.get_diamond_stats.return_value = (DiamondStatsRow("a" * 32, "Alice", 1, 0),)
        MiningMaterialDaily.objects.create(
            date="2026-09-01",
            player_uuid="a" * 32,
            world_id=87,
            material_key="stone",
            break_count=10,
        )
        self.repo.get_denominator_stats.return_value = (
            MaterialBreakRow("a" * 32, "Alice", (10, 0)),
        )

    def test_target_player_visible_with_neutral_sample_and_ratios(self):
        response = self.client.get("/ore-statistics/diamonds/")
        for text in (
            "Alice",
            "Small sample",
            "Stone",
            "Diamonds per 1,000",
            "100.00",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "No natural diamond mining events matched")

    def test_two_tables_have_independent_membership_and_no_combined_columns(self):
        self.repo.get_diamond_stats.return_value = (
            DiamondStatsRow("a" * 32, "NormalOnly", 1, 0),
            DiamondStatsRow("b" * 32, "DeepOnly", 0, 2),
            DiamondStatsRow("c" * 32, "Both", 3, 4),
        )
        response = self.client.get("/ore-statistics/diamonds/")
        html = response.content.decode()
        normal, deep = html.split('id="deepslate-diamonds-heading"')
        normal = normal.split('id="normal-diamonds-heading"')[1]
        self.assertIn("NormalOnly", normal)
        self.assertNotIn("DeepOnly", normal)
        self.assertIn("DeepOnly", deep)
        self.assertNotIn("NormalOnly", deep)
        self.assertIn("Both", normal)
        self.assertIn("Both", deep)
        self.assertEqual(html.count('scope="col"'), 10)
        self.assertNotContains(response, "Total Base Blocks")
        self.repo.get_denominator_stats.assert_not_called()

    def test_uninitialized_and_stale_states_never_use_live_all_time_fallback(self):
        MiningAnalyticsSyncState.objects.update(initialized=False)
        response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "are initializing", status_code=503)
        self.assertNotContains(response, 'class="statistics-table', status_code=503)
        self.repo.get_denominator_stats.assert_not_called()
        MiningAnalyticsSyncState.objects.update(initialized=True, last_error="Safe error")
        response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "Base-block analytics may be stale")
        self.assertContains(response, "Recent rollback reconciliation:")

    def test_denominator_only_results_show_empty_natural_mining_state(self):
        self.repo.get_diamond_stats.return_value = ()
        response = self.client.get("/ore-statistics/diamonds/")
        self.assertNotContains(response, "Alice")
        self.assertContains(response, "No natural diamond mining events matched this range.")
        self.assertEqual(response.context["report"].query.start, None)
        self.assertEqual(response.context["range_label"], "All time")

    def test_denominator_only_player_hidden_alongside_qualifying_player(self):
        self.repo.get_denominator_stats.return_value += (
            MaterialBreakRow("b" * 32, "BaseOnlyBob", (1000, 2000)),
        )
        response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "BaseOnlyBob")

    def test_denominator_failure_is_generic_not_partial_or_empty(self):
        with patch(
            "analytics.services.rollups.read_snapshot",
            side_effect=RollupUnavailable("Base-block analytics are unavailable."),
        ):
            response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "Base-block analytics unavailable", status_code=503)
        self.assertNotContains(response, "No natural diamond", status_code=503)
        self.repo.get_denominator_stats.assert_not_called()

    def test_postgres_error_is_generic_and_never_triggers_live_fallback(self):
        with patch(
            "analytics.services.rollups.read_snapshot", side_effect=DatabaseError("password=secret")
        ):
            response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "Base-block analytics unavailable", status_code=503)
        self.assertNotContains(response, "password=secret", status_code=503)
        self.repo.get_denominator_stats.assert_not_called()

    def test_picker_sticky_structure_and_primary_dashboard_action(self):
        response = self.client.get("/ore-statistics/diamonds/")
        for text in (
            "statistics-scroll",
            "statistics-table",
            'aria-labelledby="range-title"',
            "Choose custom range",
            "End time (UTC)",
            "mining-range.js",
            "mining-clock.js",
            'aria-labelledby="clock-title"',
            'role="slider"',
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, 'type="datetime-local"')
        self.assertContains(response, '<input id="precise-start" type="hidden">', html=True)
        self.assertContains(response, '<input id="precise-end" type="hidden">', html=True)
        dashboard = self.client.get("/")
        self.assertContains(
            dashboard, 'class="button primary"\n           href="/ore-statistics/diamonds/"'
        )
        self.assertContains(dashboard, "Open mining statistics")

    def test_server_rejects_invalid_dates_without_javascript(self):
        for data in (
            {"range": "custom", "start": "2026-02-30", "end": "2026-03-01"},
            {"range": "custom", "start": "2026-09-12", "end": "2026-09-10"},
            {"world": "999"},
        ):
            self.assertEqual(self.client.get("/ore-statistics/diamonds/", data).status_code, 400)
        self.repo.get_denominator_stats.assert_not_called()
