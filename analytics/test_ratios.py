from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from accounts.discord import Membership
from accounts.models import User
from coreprotect.mining import DIAMONDS, SMALL_SAMPLE_BASE_BLOCKS, DiamondStatsRow, MaterialBreakRow
from coreprotect.repository import CoreProtectUnavailable, World

from .forms import DiamondFiltersForm
from .services import get_report, merge_diamond_rows
from .templatetags.mining import mining_ratio


class RatioTests(SimpleTestCase):
    def test_full_union_and_uuid_normalization(self):
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
                DiamondStatsRow("c" * 32, "Carol", 0, 0, 10, 20),
            ),
        )

    def test_all_ratio_formulas(self):
        row = DiamondStatsRow("a" * 32, "Alice", 2, 3, 100, 300)
        self.assertEqual((row.total, row.total_base_blocks), (5, 400))
        self.assertEqual(row.diamonds_per_1000, Decimal("12.5"))
        self.assertEqual(row.base_blocks_per_diamond, 80)
        self.assertEqual(row.stone_per_normal_diamond, 50)
        self.assertEqual(row.deepslate_per_deep_diamond, 100)

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

    def test_ties_order_by_name_then_uuid_including_base_only_players(self):
        rows = merge_diamond_rows(
            (),
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
        repo = factory.return_value
        repo.get_diamond_stats.return_value = (DiamondStatsRow("a" * 32, "Alice", 1, 0),)
        repo.get_denominator_stats.side_effect = CoreProtectUnavailable("secret")
        form = DiamondFiltersForm({"range": "24h"}, worlds=())
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
        self.repo.get_diamond_stats.return_value = ()
        self.repo.get_denominator_stats.return_value = (
            MaterialBreakRow("a" * 32, "Alice", (10, 0)),
        )

    def test_base_only_player_visible_with_neutral_sample_and_ratios(self):
        response = self.client.get("/ore-statistics/diamonds/")
        for text in (
            "Alice",
            "Small sample",
            "Total Base Blocks",
            "Diamonds per 1,000",
            "—",
            "0.00",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "No natural diamond mining events matched")

    def test_denominator_failure_is_generic_not_partial_or_empty(self):
        self.repo.get_denominator_stats.side_effect = CoreProtectUnavailable("SQL host-secret")
        response = self.client.get("/ore-statistics/diamonds/")
        self.assertContains(response, "CoreProtect analytics unavailable", status_code=503)
        self.assertNotContains(response, "host-secret", status_code=503)
        self.assertNotContains(response, "No natural diamond", status_code=503)

    def test_picker_sticky_structure_and_primary_dashboard_action(self):
        response = self.client.get("/ore-statistics/diamonds/")
        for text in (
            "statistics-scroll",
            "statistics-table",
            'aria-labelledby="range-title"',
            "Choose custom range",
            "Exact end (UTC, exclusive)",
            "mining-range.js",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, 'type="datetime-local"')
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
