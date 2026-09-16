from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.discord import DiscordUnavailable, Membership
from accounts.models import GuildAuthorization, User
from coreprotect.mining import DiamondQuery, DiamondStatsRow
from coreprotect.repository import CoreProtectUnavailable, World

from .forms import DiamondFiltersForm
from .services import CACHE_SECONDS, get_report, list_worlds
from .test_rollups import ready_state

WORLDS = (World(802, "resource_world"), World(1701, "archived_world"))
NOW = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
ROWS = (DiamondStatsRow("a" * 32, "Alice", 1234, 5678),)


class FilterTests(SimpleTestCase):
    def form(self, data):
        return DiamondFiltersForm(data, worlds=WORLDS)

    def test_default_is_all_history_all_worlds(self):
        form = self.form({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.to_query(now=NOW), DiamondQuery())

    def test_quick_ranges_use_one_consistent_now(self):
        for name, days in (("24h", 1), ("7d", 7), ("30d", 30)):
            with self.subTest(name=name):
                query = self.form({"range": name}).to_query(now=NOW)
                self.assertEqual(query.start, NOW - timedelta(days=days))
                self.assertEqual(query.end, NOW)

    def test_custom_datetimes_are_utc_even_if_active_timezone_is_not(self):
        with timezone.override(ZoneInfo("Pacific/Honolulu")):
            form = self.form(
                {"range": "custom", "start": "2026-09-01T12:00", "end": "2026-09-02T12:00"}
            )
            query = form.to_query(now=NOW)
        self.assertEqual(query.start, datetime(2026, 9, 1, 12, tzinfo=UTC))
        self.assertEqual(query.end, datetime(2026, 9, 2, 12, tzinfo=UTC))

    def test_explicit_offsets_normalize_to_utc(self):
        query = self.form(
            {
                "range": "custom",
                "start": "2026-09-01T14:00:00+02:00",
                "end": "2026-09-02T14:00:00+02:00",
            }
        ).to_query(now=NOW)
        self.assertEqual(query.start, datetime(2026, 9, 1, 12, tzinfo=UTC))

    def test_custom_date_only_uses_midnight(self):
        query = self.form({"range": "custom", "start": "2026-09-01", "end": "2026-09-02"}).to_query(
            now=NOW
        )
        self.assertEqual(query.end, datetime(2026, 9, 2, tzinfo=UTC))

    def test_bad_ranges_and_worlds_are_rejected(self):
        for data in (
            {"range": "bad"},
            {"world": "1 OR 1=1"},
            {"world": "999"},
            {"world": "-1"},
            {"world": "802.0"},
            {"range": "custom"},
            {"range": "custom", "start": "2026-09-01"},
            {"range": "custom", "end": "2026-09-02"},
        ):
            with self.subTest(data=data):
                form = self.form(data)
                self.assertFalse(form.is_valid())
                with self.assertRaises(ValueError):
                    form.to_query(now=NOW)

    def test_invalid_custom_bounds(self):
        for start, end in (
            ("2026-09-03", "2026-09-02"),
            ("2026-09-01", "2026-09-01"),
            ("garbage", "2026-09-02"),
            ("2026-02-30", "2026-09-02"),
            ("x" * 200, "2026-09-02"),
            ("0001-01-01T00:00:00+23:00", "2026-09-02"),
        ):
            with self.subTest(start=start, end=end):
                self.assertFalse(
                    self.form({"range": "custom", "start": start, "end": end}).is_valid()
                )

    def test_custom_bounds_cannot_be_silently_ignored_by_quick_range(self):
        self.assertFalse(self.form({"range": "7d", "start": "2026-09-01"}).is_valid())

    def test_world_choices_are_mapping_driven(self):
        form = self.form({"world": "1701"})
        self.assertEqual(form.to_query(now=NOW).world_id, 1701)
        self.assertIn(("802", "resource_world"), form.fields["world"].choices)
        later = DiamondFiltersForm({"world": "9191"}, worlds=(*WORLDS, World(9191, "new_world")))
        self.assertEqual(later.to_query(now=NOW).world_id, 9191)

    def test_semantic_query_rejects_unsafe_bounds(self):
        for kwargs in (
            {"start": datetime(2026, 1, 1)},
            {"world_id": "SQL"},
            {"world_id": -1},
            {"world_id": True},
            {"start": NOW, "end": NOW},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DiamondQuery(**kwargs)


class CacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.patcher = patch("analytics.services.get_repository")
        self.factory = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.repository = self.factory.return_value
        self.repository.get_diamond_stats.return_value = ROWS
        ready_state()
        self.repository.get_denominator_stats.return_value = ()
        self.repository.list_worlds.return_value = list(WORLDS)

    def form(self, data):
        return DiamondFiltersForm(data, worlds=WORLDS)

    def test_equivalent_default_filters_share_cache(self):
        self.assertEqual(
            get_report(self.form({})), get_report(self.form({"range": "all", "world": ""}))
        )
        self.repository.get_diamond_stats.assert_called_once()

    def test_quick_range_uses_cached_exact_bounds_as_now_moves(self):
        with patch("analytics.services.timezone.now", return_value=NOW):
            first = get_report(self.form({"range": "24h"}))
        with patch("analytics.services.timezone.now", return_value=NOW + timedelta(seconds=20)):
            second = get_report(self.form({"range": "24h"}))
        self.assertEqual(first, second)
        self.assertEqual(second.query.end, NOW)
        self.repository.get_diamond_stats.assert_called_once()

    def test_ranges_and_worlds_do_not_collide(self):
        for data in (
            {},
            {"range": "24h"},
            {"range": "7d"},
            {"range": "30d"},
            {"range": "24h", "world": "802"},
            {"range": "24h", "world": "1701"},
        ):
            get_report(self.form(data))
        self.assertEqual(self.repository.get_diamond_stats.call_count, 6)

    def test_custom_start_end_and_world_do_not_collide(self):
        defaults = {"range": "custom", "start": "2026-09-01", "end": "2026-09-10"}
        for changes in ({}, {"start": "2026-09-02"}, {"end": "2026-09-11"}, {"world": "802"}):
            get_report(self.form({**defaults, **changes}))
        self.assertEqual(self.repository.get_diamond_stats.call_count, 4)

    def test_equivalent_offset_bounds_share_cache(self):
        first = get_report(
            self.form(
                {"range": "custom", "start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z"}
            )
        )
        second = get_report(
            self.form(
                {
                    "range": "custom",
                    "start": "2026-09-01T02:00:00+02:00",
                    "end": "2026-09-02T02:00:00+02:00",
                }
            )
        )
        self.assertEqual(first, second)
        self.repository.get_diamond_stats.assert_called_once()

    def test_cache_expires_and_world_choices_refresh(self):
        with patch("django.core.cache.backends.locmem.time.time", return_value=1000):
            first = get_report(self.form({}))
            self.assertEqual(list_worlds(), WORLDS)
        self.repository.get_diamond_stats.return_value = ()
        self.repository.list_worlds.return_value = [*WORLDS, World(5000, "new_world")]
        with patch(
            "django.core.cache.backends.locmem.time.time", return_value=1000 + CACHE_SECONDS + 1
        ):
            self.assertNotEqual(get_report(self.form({})), first)
            self.assertIn(World(5000, "new_world"), list_worlds())
        self.assertEqual(self.repository.get_diamond_stats.call_count, 2)

    def test_cached_rows_contain_no_configuration_or_secrets(self):
        with patch("analytics.services.cache.set") as store:
            get_report(self.form({"range": "7d"}))
        key, report = store.call_args.args
        self.assertTrue(key.startswith("mining:v5:report:"))
        self.assertEqual(
            set(vars(report)),
            {
                "query",
                "rows",
                "checked_at",
                "base_updated_at",
                "base_reconciled_at",
                "base_warning",
            },
        )
        self.assertEqual(store.call_args.kwargs, {"timeout": 45})

    def test_cache_read_write_failure_falls_back_to_fresh_query(self):
        with (
            patch("analytics.services.cache.get", side_effect=RuntimeError("cache down")),
            patch("analytics.services.cache.set", side_effect=RuntimeError("cache down")),
        ):
            self.assertEqual(list_worlds(), WORLDS)
            self.assertEqual(get_report(self.form({})).rows, ROWS)

    def test_repository_failure_does_not_cache_fake_empty_result(self):
        self.repository.get_diamond_stats.side_effect = CoreProtectUnavailable("secret")
        with patch("analytics.services.cache.set") as store:
            with self.assertRaises(CoreProtectUnavailable):
                get_report(self.form({}))
            store.assert_not_called()
        self.repository.get_diamond_stats.side_effect = None
        self.assertEqual(get_report(self.form({})).rows, ROWS)

    def test_successful_empty_result_is_cached(self):
        self.repository.get_diamond_stats.return_value = ()
        self.assertEqual(get_report(self.form({})).rows, ())
        self.assertEqual(get_report(self.form({})).rows, ())
        self.repository.get_diamond_stats.assert_called_once()


class DiamondPageTests(TestCase):
    url = "/ore-statistics/diamonds/"

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("123", username="Staff")
        self.repo_patch = patch("analytics.services.get_repository")
        self.repository = self.repo_patch.start().return_value
        self.addCleanup(self.repo_patch.stop)
        self.repository.list_worlds.return_value = WORLDS
        self.repository.get_diamond_stats.return_value = ROWS
        ready_state()
        self.repository.get_denominator_stats.return_value = ()
        self.member_patch = patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))
        )
        self.membership = self.member_patch.start()
        self.addCleanup(self.member_patch.stop)

    def login(self):
        self.client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")

    def test_unauthenticated_cannot_access_or_query(self):
        self.assertRedirects(self.client.get(self.url), "/auth/login/")
        self.repository.list_worlds.assert_not_called()

    def test_admin_and_overlord_can_access(self):
        self.login()
        for role in ("200", "300"):
            with self.subTest(role=role):
                GuildAuthorization.objects.all().delete()
                self.membership.return_value = Membership(True, (role,))
                response = self.client.get(self.url)
                self.assertContains(response, "Diamond Mining Statistics")
                self.assertContains(response, "1,234")
                self.assertContains(response, "5,678")
                self.assertContains(response, "Normal Diamond Mining")
                self.assertContains(response, "Deepslate Diamond Mining")

    def test_patron_and_ordinary_member_cannot_access(self):
        self.login()
        for roles in (("400",), ()):
            with self.subTest(roles=roles):
                GuildAuthorization.objects.all().delete()
                self.membership.return_value = Membership(True, roles)
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.repository.list_worlds.assert_not_called()

    def test_cached_report_does_not_bypass_role_revocation(self):
        self.login()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        GuildAuthorization.objects.update(checked_at=timezone.now() - timedelta(seconds=61))
        self.membership.return_value = Membership(True, ())
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.repository.get_diamond_stats.assert_called_once()

    def test_discord_failure_does_not_use_cached_report(self):
        self.login()
        self.client.get(self.url)
        GuildAuthorization.objects.update(checked_at=timezone.now() - timedelta(seconds=61))
        self.membership.side_effect = DiscordUnavailable()
        response = self.client.get(self.url)
        self.assertContains(response, "Access verification unavailable", status_code=503)
        self.assertNotContains(response, "Alice", status_code=503)

    def test_page_uses_analytics_permission_not_just_portal_access(self):
        self.login()
        with patch("accounts.permissions.authorization_for", return_value={"portal.access"}):
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_dynamic_world_selected_and_active_context_visible(self):
        self.login()
        with patch("analytics.services.timezone.now", return_value=NOW):
            response = self.client.get(self.url, {"range": "7d", "world": "1701"})
        self.assertContains(response, "Last 7 days")
        self.assertContains(response, "archived_world")
        self.assertContains(response, "resource_world")
        self.assertContains(response, "2026-09-07 12:30:00")
        self.repository.get_diamond_stats.assert_called_once_with(
            DiamondQuery(NOW - timedelta(days=7), NOW, 1701),
        )

    def test_invalid_world_and_range_do_not_query_analytics(self):
        self.login()
        for data in ({"world": "9999"}, {"range": "bad"}, {"range": "custom", "start": "bad"}):
            with self.subTest(data=data):
                response = self.client.get(self.url, data)
                self.assertContains(response, "Please correct the filters", status_code=400)
                self.assertNotContains(response, "No natural diamond", status_code=400)
        self.repository.get_diamond_stats.assert_not_called()

    def test_empty_success_is_distinct_from_failure(self):
        self.login()
        self.repository.get_diamond_stats.return_value = ()
        response = self.client.get(self.url)
        self.assertContains(response, "No natural diamond mining events matched this range.")
        self.assertNotContains(response, "CoreProtect analytics unavailable")

    def test_coreprotect_failure_preserves_shell_without_sensitive_error_text(self):
        self.login()
        self.repository.get_diamond_stats.side_effect = CoreProtectUnavailable(
            "SELECT secret-host password=test-secret"
        )
        response = self.client.get(self.url)
        self.assertContains(response, "CoreProtect analytics unavailable", status_code=503)
        self.assertContains(response, 'id="sidebar"', status_code=503)
        for secret in ("secret-host", "test-secret", "SELECT"):
            self.assertNotContains(response, secret, status_code=503)
        self.assertEqual(self.client.get("/docs/code-of-conduct/").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_world_lookup_failure_also_renders_safe_unavailable_state(self):
        self.login()
        self.repository.list_worlds.side_effect = CoreProtectUnavailable("secret-host")
        response = self.client.get(self.url)
        self.assertContains(response, "CoreProtect analytics unavailable", status_code=503)
        self.assertNotContains(response, "secret-host", status_code=503)
        self.repository.get_diamond_stats.assert_not_called()

    def test_player_and_world_labels_are_escaped(self):
        self.login()
        self.repository.list_worlds.return_value = [World(802, "<script>bad</script>")]
        self.repository.get_diamond_stats.return_value = [
            DiamondStatsRow("a" * 32, "<img src=x>", 1, 0)
        ]
        response = self.client.get(self.url, {"world": "802"})
        self.assertContains(response, "&lt;img src=x&gt;")
        self.assertNotContains(response, "<script>bad</script>")

    def test_navigation_and_dashboard_link_to_real_feature(self):
        self.login()
        response = self.client.get("/")
        self.assertContains(response, 'href="/ore-statistics/"')
        self.assertNotContains(response, "Ore analytics not configured yet")
        self.assertContains(response, "Live Ore Activity")

    def test_cached_range_label_matches_original_query_time(self):
        self.login()
        with patch("analytics.services.timezone.now", return_value=NOW):
            self.client.get(self.url, {"range": "24h"})
        with patch("analytics.services.timezone.now", return_value=NOW + timedelta(seconds=20)):
            response = self.client.get(self.url, {"range": "24h"})
        self.assertContains(response, "2026-09-14 12:30:00")
        self.assertNotContains(response, "2026-09-14 12:30:20")
