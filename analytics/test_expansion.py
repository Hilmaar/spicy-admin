from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts.discord import Membership
from accounts.models import User
from coreprotect.mining import ANCIENT_DEBRIS, EMERALD, DiamondStatsRow, MaterialBreakRow
from coreprotect.repository import CoreProtectUnavailable, World
from coreprotect.test_rollup import RollupFixture

from .forms import DiamondFiltersForm
from .models import MiningAnalyticsSyncState, MiningMaterialDaily
from .ore_config import PAGES, SAMPLE_OPTIONS
from .services import MiningLayerRow, get_report, overview_metric, report_tables, sort_layer
from .sync import sync_mining
from .test_rollups import ready_state


class ExpansionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        ready_state()
        factory = patch("analytics.services.get_repository")
        self.repo = factory.start().return_value
        self.addCleanup(factory.stop)
        self.repo.list_worlds.return_value = (World(83, "world"), World(927, "world_nether"))
        self.repo.get_diamond_stats.return_value = (DiamondStatsRow("a" * 32, "Alice", 2, 3),)
        self.repo.get_material_stats.return_value = (MaterialBreakRow("a" * 32, "Alice", (4,)),)
        self.repo.get_denominator_stats.return_value = ()
        roles = patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))
        )
        roles.start()
        self.addCleanup(roles.stop)
        user = User.objects.create_user("991", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        for key, count in (("stone", 1000), ("deepslate", 2000), ("netherrack", 4000)):
            MiningMaterialDaily.objects.create(
                date="2026-09-01",
                player_uuid="a" * 32,
                world_id=83,
                material_key=key,
                break_count=count,
            )

    def test_debris_all_time_uses_netherrack_rollup_and_single_layer(self):
        report = get_report(DiamondFiltersForm({}, worlds=()), ANCIENT_DEBRIS)
        table = report_tables(report, PAGES[1])[0]
        row = table["rows"][0]
        self.assertEqual(
            (row.target_count, row.base_count, row.per_1000, row.per_target), (4, 4000, 1, 1000)
        )
        self.repo.get_denominator_stats.assert_not_called()
        self.repo.get_material_stats.assert_called_once_with(
            report.query, ANCIENT_DEBRIS.target_materials, natural_only=True
        )
        response = self.client.get(PAGES[1].url)
        self.assertContains(response, "Ancient Debris per 1,000 Netherrack")
        self.assertContains(response, 'data-table-key="ancient-debris"')

    def test_emerald_layers_filter_membership_and_use_existing_base_materials(self):
        self.repo.get_material_stats.return_value = (
            MaterialBreakRow("a" * 32, "Alice", (10, 2)),
            MaterialBreakRow("b" * 32, "NormalOnly", (1, 0)),
            MaterialBreakRow("c" * 32, "DeepOnly", (0, 1)),
        )
        tables = report_tables(get_report(DiamondFiltersForm({}, worlds=()), EMERALD), PAGES[2])
        self.assertEqual([r.player_name for r in tables[0]["rows"]], ["Alice", "DeepOnly"])
        self.assertEqual([r.player_name for r in tables[1]["rows"]], ["Alice", "NormalOnly"])
        self.assertEqual(tables[0]["rows"][0].per_1000, 1)
        self.assertEqual(tables[1]["rows"][0].per_1000, 10)
        self.repo.get_denominator_stats.assert_not_called()
        response = self.client.get(PAGES[2].url)
        html = response.content.decode()
        self.assertLess(
            html.index('id="deepslate-emerald-heading"'), html.index('id="normal-emerald-heading"')
        )

    def test_precise_bounds_world_and_cache_group_isolation(self):
        form = DiamondFiltersForm(
            {
                "range": "custom",
                "world": "83",
                "start": "2026-09-01T14:30Z",
                "end": "2026-09-03T18:15Z",
            },
            worlds=(World(83, "world"), World(927, "world_nether")),
        )
        get_report(form, ANCIENT_DEBRIS)
        calls = self.repo.get_denominator_stats.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0].start, datetime(2026, 9, 1, 14, 30, tzinfo=UTC))
        self.assertEqual(calls[1].args[0].end, datetime(2026, 9, 3, 18, 15, tzinfo=UTC))
        self.assertTrue(
            all(c.args[0].world_id == 83 and c.args[1] == ANCIENT_DEBRIS for c in calls)
        )
        self.repo.get_material_stats.return_value = (MaterialBreakRow("a" * 32, "Alice", (1, 2)),)
        get_report(form, EMERALD)
        get_report(form, EMERALD)
        self.assertEqual(self.repo.get_material_stats.call_count, 2)

    def test_overview_union_totals_no_rollups_or_denominators(self):
        self.repo.get_diamond_stats.return_value = (
            DiamondStatsRow("a" * 32, "Alice", 2, 0),
            DiamondStatsRow("A" * 32, "OldAlice", 0, 3),
            DiamondStatsRow("b" * 32, "Bob", 1, 1),
        )
        with patch(
            "analytics.services.rollups.read_snapshot", side_effect=AssertionError("no rollups")
        ):
            response = self.client.get("/ore-statistics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (
                response.context["cards"][0]["metric"].total,
                response.context["cards"][0]["metric"].players,
            ),
            (7, 2),
        )
        for page in PAGES:
            self.assertContains(response, f"material-{page.slug}")
            self.assertContains(response, f'href="{page.url}"')
        self.assertContains(response, 'aria-label="Ore materials"')
        self.assertContains(response, 'class="material-gem"')
        self.repo.get_denominator_stats.assert_not_called()
        overview_metric(ANCIENT_DEBRIS)
        self.assertEqual(self.repo.get_material_stats.call_count, 2)

    def test_overview_source_failure_is_not_cached_as_zero(self):
        self.repo.get_material_stats.side_effect = CoreProtectUnavailable("password=secret")
        response = self.client.get("/ore-statistics/")
        self.assertContains(response, "Statistics unavailable")
        self.assertNotContains(response, "password=secret")
        self.repo.get_material_stats.side_effect = None
        self.assertEqual(overview_metric(ANCIENT_DEBRIS).total, 4)

    def test_each_page_uses_configured_world_and_ignores_client_world(self):
        self.repo.get_material_stats.return_value = ()
        for page in PAGES:
            with self.subTest(page=page.slug):
                response = self.client.get(page.url, {"world": "999"})
                expected = 927 if page.slug == "ancient-debris" else 83
                self.assertEqual(response.context["report"].query.world_id, expected)
                self.assertIsNone(response.context["report"].query.start)
                for removed in (
                    'id="id_world"',
                    "Queried at",
                    "Select both dates",
                    "Recent rollback reconciliation:",
                ):
                    self.assertNotContains(response, removed)

    def test_missing_or_ambiguous_configured_world_never_falls_back_to_all_worlds(self):
        for worlds in ((World(99, "resource_world"),), (World(83, "world"), World(99, "world"))):
            cache.clear()
            self.repo.list_worlds.return_value = worlds
            response = self.client.get(PAGES[0].url)
            self.assertContains(response, "CoreProtect analytics unavailable", status_code=503)
        self.repo.get_diamond_stats.assert_not_called()

    def test_dynamic_world_mapping_changes_report_cache_identity(self):
        first = self.client.get(PAGES[0].url, {"world": "100"})
        second = self.client.get(PAGES[0].url, {"world": "200"})
        self.assertEqual(first.context["report"].query, second.context["report"].query)
        self.repo.get_diamond_stats.assert_called_once()
        # Change only the world lookup cache; the old successful report remains cached.
        with patch("analytics.services.list_worlds", return_value=(World(528, "world"),)):
            changed = self.client.get(PAGES[0].url)
        self.assertEqual(changed.context["report"].query.world_id, 528)
        self.assertEqual(self.repo.get_diamond_stats.call_count, 2)

    def test_emerald_overview_union_and_base_only_debris_players(self):
        self.repo.get_material_stats.return_value = (
            MaterialBreakRow("a" * 32, "Alice", (2, 0)),
            MaterialBreakRow("A" * 32, "PreviousAlice", (0, 3)),
            MaterialBreakRow("b" * 32, "Bob", (0, 1)),
            MaterialBreakRow("c" * 32, "Zero", (0, 0)),
        )
        metric = overview_metric(EMERALD)
        self.assertEqual((metric.total, metric.players), (6, 2))
        MiningMaterialDaily.objects.create(
            date="2026-09-01",
            player_uuid="b" * 32,
            world_id=83,
            material_key="netherrack",
            break_count=9000,
        )
        self.repo.get_material_stats.return_value = (MaterialBreakRow("a" * 32, "Alice", (4,)),)
        report = get_report(DiamondFiltersForm({}, worlds=()), ANCIENT_DEBRIS)
        self.assertEqual([r.player_name for r in report.rows], ["Alice"])

    def test_new_groups_share_bootstrap_guard_but_overview_remains_available(self):
        MiningAnalyticsSyncState.objects.update(initialized=False)
        for page in PAGES[1:]:
            response = self.client.get(page.url)
            self.assertContains(response, "are initializing", status_code=503)
        self.repo.get_material_stats.assert_not_called()
        self.repo.get_denominator_stats.assert_not_called()
        self.assertEqual(self.client.get("/ore-statistics/").status_code, 200)

    def test_permissions_guard_every_new_route_and_overview(self):
        with patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("400",))
        ):
            # Clear the per-session shared membership revalidation cache.
            from accounts.models import GuildAuthorization

            GuildAuthorization.objects.all().delete()
            for url in ("/ore-statistics/", PAGES[1].url, PAGES[2].url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.repo.get_material_stats.assert_not_called()

    def test_defaults_threshold_options_and_small_sample_ratio_order(self):
        self.assertEqual(SAMPLE_OPTIONS, (250, 500, 1000, 2500, 5000, 10000))
        self.assertTrue(all(t.default_threshold == 1000 for p in PAGES for t in p.tables))
        configured = replace(
            PAGES[1], tables=(replace(PAGES[1].tables[0], default_threshold=5000),)
        )
        report = get_report(DiamondFiltersForm({}, worlds=()), ANCIENT_DEBRIS)
        self.assertTrue(report_tables(report, configured)[0]["rows"][0].small_sample)
        self.assertFalse(report_tables(report, PAGES[1])[0]["rows"][0].small_sample)
        rows = [
            MiningLayerRow("c", "Carol", 100, 100),
            MiningLayerRow("b", "Bob", 10, 2000),
            MiningLayerRow("a", "Alice", 5, 1000),
            MiningLayerRow("d", "Zero", 99, 0),
        ]
        self.assertEqual(
            [r.player_name for r in sort_layer(rows)], ["Alice", "Bob", "Carol", "Zero"]
        )
        with self.assertRaises(ValueError):
            replace(PAGES[0].tables[0], default_threshold=999)


class NetherrackSyncTests(RollupFixture, TestCase):
    def test_recent_netherrack_rollback_reconciles_without_duplicate_forward_counts(self):
        now = int(timezone.now().timestamp())
        self.event(material=self.netherrack, time=now)
        with patch("analytics.sync.get_repository", return_value=self.repository):
            sync_mining()
            self.db.execute("UPDATE co_block SET rolled_back=1")
            sync_mining(reconcile_only=True)
            self.assertFalse(MiningMaterialDaily.objects.exists())
            self.event(material=self.netherrack, time=now)
            sync_mining()
            sync_mining()
            self.assertEqual(MiningMaterialDaily.objects.get().break_count, 1)

    def test_netherrack_uses_existing_backfill_incremental_reconcile_and_rebuild(self):
        self.event(material=self.netherrack, time=100, action=1)
        self.event(material=self.netherrack, time=101)
        with patch("analytics.sync.get_repository", return_value=self.repository):
            sync_mining()
            self.assertEqual(
                MiningMaterialDaily.objects.get(material_key="netherrack").break_count, 1
            )
            self.event(material=self.netherrack, time=102)
            sync_mining()
            self.assertEqual(
                MiningMaterialDaily.objects.get(material_key="netherrack").break_count, 2
            )
            self.db.execute("UPDATE co_block SET rolled_back=1")
            sync_mining(full_rebuild=True)
            self.assertFalse(MiningMaterialDaily.objects.exists())
