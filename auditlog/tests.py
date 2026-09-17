import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.discord import DiscordUnavailable, Membership
from accounts.models import GuildAuthorization, User
from analytics.ore_config import PAGES
from analytics.test_rollups import ready_state
from coreprotect.repository import World

from .events import EventType, Result
from .models import AuditEvent
from .service import client_ip, record


class AuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "123456789", username="Staff", display_name="Team member"
        )
        self.client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")
        mock = patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))
        )
        self.membership = mock.start()
        self.addCleanup(mock.stop)

    def event(self, **kwargs):
        return AuditEvent.objects.create(
            **{
                "event_type": EventType.DASHBOARD,
                "result": Result.SUCCESS,
                "actor_discord_id": self.user.discord_id,
                "actor_username": self.user.username,
                "request_method": "GET",
                "request_path": "/",
                **kwargs,
            }
        )

    def test_admin_access_summary_four_columns_and_protected_detail(self):
        event = self.event(metadata_json={"private": "<script>alert(1)</script>"})
        response = self.client.get("/audit-log/")
        self.assertContains(response, 'href="/audit-log/"')
        self.assertEqual(response.content.decode().count('scope="col"'), 4)
        self.assertNotContains(response, "<script>alert")
        self.assertNotContains(response, "Event metadata")
        detail = self.client.get(f"/audit-log/{event.pk}/")
        self.assertContains(detail, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(detail, "<script>alert")
        payload = self.client.get(f"/audit-log/{event.pk}/?format=json").json()
        self.assertEqual(dict(payload["details"])["Discord ID"], self.user.discord_id)
        self.assertEqual(self.client.get("/audit-log/999999/?format=json").status_code, 404)

    def test_all_audit_read_routes_require_admin_even_for_overlord(self):
        event = self.event()
        for roles in (("300",), ("400",), ()):
            GuildAuthorization.objects.all().delete()
            self.membership.return_value = Membership(True, roles)
            for path in (
                "/audit-log/",
                f"/audit-log/{event.pk}/",
                f"/audit-log/{event.pk}/?format=json",
            ):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.client.logout()
        self.assertRedirects(self.client.get("/audit-log/"), "/auth/login/")

    def test_empty_list_and_invalid_filters(self):
        self.assertContains(self.client.get("/audit-log/"), "No events matched these filters.")
        for data in (
            {"range": "bad"},
            {"event_type": "anything"},
            {"result": "bad"},
            {"page_size": "999"},
            {"actor": "unknown"},
            {"range": "custom", "start": "bad"},
        ):
            self.assertEqual(self.client.get("/audit-log/", data).status_code, 400)

    def test_default_seven_days_and_newest_first_pagination_preserves_filters(self):
        now = timezone.now()
        self.event(created_at=now - timedelta(days=8))
        for i in range(105):
            self.event(created_at=now - timedelta(seconds=i + 1))
        response = self.client.get("/audit-log/")
        page = response.context["page"]
        self.assertEqual((len(page), page.paginator.count), (100, 105))
        self.assertGreater(page[0].created_at, page[-1].created_at)
        response = self.client.get(
            "/audit-log/",
            {
                "range": "all",
                "page_size": "50",
                "page": "2",
                "actor": self.user.discord_id,
                "event_type": EventType.DASHBOARD,
                "result": Result.SUCCESS,
                "code": "secret",
            },
        )
        self.assertEqual(len(response.context["page"]), 50)
        self.assertContains(response, "range=all")
        self.assertContains(response, "page_size=50")
        self.assertContains(response, "actor=123456789")
        self.assertNotContains(response, "code=secret")
        self.assertEqual(self.client.get("/audit-log/", {"page": "nonsense"}).status_code, 200)

    def test_all_audit_presets_and_filter_form_persist(self):
        now = timezone.now()
        for days in (0, 2, 8, 31):
            self.event(created_at=now - timedelta(days=days, minutes=1))
        for preset, count in (("24h", 1), ("7d", 2), ("30d", 3), ("all", 4)):
            response = self.client.get("/audit-log/", {"range": preset, "page_size": "50"})
            self.assertEqual(response.context["page"].paginator.count, count)
            self.assertEqual(response.context["form"]["range"].value(), preset)
            self.assertEqual(response.context["form"]["page_size"].value(), "50")

    def test_relative_range_includes_events_from_current_second(self):
        now = timezone.now().replace(microsecond=500000)
        event = self.event(created_at=now - timedelta(microseconds=1))
        with patch("auditlog.views.timezone.now", return_value=now):
            response = self.client.get("/audit-log/")
        self.assertEqual(list(response.context["page"]), [event])

    @override_settings(AUDIT_LOG_RETENTION_DAYS=10)
    def test_custom_retention_is_respected(self):
        self.event(created_at=timezone.now() - timedelta(days=11))
        retained = self.event(created_at=timezone.now() - timedelta(days=9))
        call_command("prune_audit_logs", stdout=StringIO())
        self.assertEqual(list(AuditEvent.objects.values_list("pk", flat=True)), [retained.pk])

    def test_anonymous_and_unprivileged_users_cannot_post_thresholds(self):
        self.client.logout()
        self.assertEqual(
            self.client.post(
                "/audit/client-event/", {}, content_type="application/json"
            ).status_code,
            302,
        )
        self.client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")
        self.membership.return_value = Membership(True, ())
        self.assertEqual(
            self.client.post(
                "/audit/client-event/", {}, content_type="application/json"
            ).status_code,
            403,
        )
        self.assertFalse(AuditEvent.objects.exists())

    def test_custom_range_uses_inclusive_start_exclusive_end_and_actor_event_result_filters(self):
        start = timezone.now() - timedelta(hours=2)
        end = start + timedelta(hours=1)
        chosen = self.event(created_at=start, result=Result.DENIED)
        self.event(created_at=end, result=Result.DENIED)
        self.event(created_at=start, result=Result.SUCCESS)
        self.event(created_at=start, result=Result.DENIED, actor_discord_id="456")
        response = self.client.get(
            "/audit-log/",
            {
                "range": "custom",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "actor": self.user.discord_id,
                "event_type": EventType.DASHBOARD,
                "result": Result.DENIED,
            },
        )
        self.assertEqual(list(response.context["page"]), [chosen])

    def test_actor_snapshot_is_preserved_after_user_rename_and_deletion(self):
        self.client.get("/")
        self.user.display_name = "Renamed"
        self.user.save()
        self.user.delete()
        event = AuditEvent.objects.get()
        self.assertEqual(event.actor_display_name, "Team member")

    def test_page_and_filtered_events_only_capture_effective_known_filters(self):
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)
        ready_state()
        with patch("analytics.services.get_repository") as factory:
            repo = factory.return_value
            repo.list_worlds.return_value = (World(91, "world"), World(782, "world_nether"))
            repo.get_diamond_stats.return_value = ()
            repo.get_material_stats.return_value = ()
            for url in ("/", "/docs/code-of-conduct/", "/ore-statistics/", *(p.url for p in PAGES)):
                self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(
                self.client.get(
                    PAGES[0].url,
                    {
                        "range": "7d",
                        "world": "attacker",
                        "thresholds": json.dumps(
                            {"normal-diamonds": 2500, "unknown": "secret", "ancient-debris": 500}
                        ),
                        "token": "secret",
                    },
                ).status_code,
                200,
            )
        expected = {
            EventType.DASHBOARD,
            EventType.CODE_OF_CONDUCT,
            EventType.ORE_OVERVIEW,
            EventType.DIAMONDS,
            EventType.ANCIENT_DEBRIS,
            EventType.EMERALD,
            EventType.FILTERED,
        }
        self.assertEqual(set(AuditEvent.objects.values_list("event_type", flat=True)), expected)
        event = AuditEvent.objects.get(event_type=EventType.FILTERED)
        self.assertEqual(event.metadata_json["configured_world"], "world")
        self.assertEqual(event.metadata_json["thresholds"], {"normal-diamonds": 2500})
        self.assertIn("start", event.metadata_json)
        self.assertIn("end", event.metadata_json)
        self.assertEqual(event.metadata_json["authorization_source"], "discord_role")
        self.assertNotIn("attacker", str(event.__dict__))
        self.assertNotIn("secret", str(event.__dict__))
        count = AuditEvent.objects.count()
        self.client.get("/healthz/")
        self.client.get("/docs/admin-cheat-sheet/")
        self.client.get("/audit-log/")
        self.assertEqual(AuditEvent.objects.count(), count)

    def test_safe_bounded_request_capture_excludes_secrets_and_arbitrary_metadata(self):
        request = RequestFactory().get(
            "/?range=7d&code=CODE&state=STATE&access_token=TOKEN&extra=SECRET",
            HTTP_REFERER="https://name:password@example.com/path?code=SECRET#SECRET",
            HTTP_USER_AGENT="x" * 900,
            HTTP_ACCEPT_LANGUAGE="en" * 200,
            HTTP_COOKIE="sessionid=SECRET",
            HTTP_AUTHORIZATION="Bearer SECRET",
        )
        request.user = self.user
        self.assertTrue(record(request, EventType.DASHBOARD, metadata={"arbitrary": "SECRET"}))
        event = AuditEvent.objects.get()
        self.assertEqual(event.request_query, {"range": "7d"})
        self.assertEqual(event.referer, "https://example.com/path")
        self.assertEqual(len(event.user_agent), 512)
        self.assertEqual(len(event.accept_language), 128)
        for secret in ("SECRET", "CODE", "STATE", "TOKEN", "password"):
            self.assertNotIn(secret, str(event.__dict__))

    def test_custom_mining_bounds_are_normalized_in_audit_metadata(self):
        request = RequestFactory().get("/ore-statistics/diamonds/")
        request.user = self.user
        record(
            request,
            EventType.FILTERED,
            metadata={
                "material_group": "diamonds",
                "range": "custom",
                "start": "2026-09-01T02:00:00.000001+02:00",
                "end": "2026-09-02T18:15Z",
            },
        )
        event = AuditEvent.objects.get()
        self.assertEqual(event.metadata_json["start"], "2026-09-01T00:00:00.000001+00:00")
        self.assertEqual(event.metadata_json["end"], "2026-09-02T18:15:00+00:00")
        self.assertEqual(event.metadata_json["configured_world"], "world")

    def test_proxy_headers_ignored_without_explicit_trusted_socket_peer(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9"
        )
        self.assertEqual(client_ip(request), "127.0.0.1")
        with override_settings(AUDIT_TRUSTED_PROXY_IPS=["127.0.0.1"]):
            self.assertEqual(client_ip(request), "203.0.113.9")
            request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.9, 192.0.2.3"
            self.assertEqual(client_ip(request), "127.0.0.1")
            request.META["HTTP_X_FORWARDED_FOR"] = "bad"
            self.assertEqual(client_ip(request), "127.0.0.1")

    def test_audit_failure_does_not_break_page_or_disclose_database_error(self):
        with patch(
            "auditlog.service.AuditEvent.objects.create", side_effect=DatabaseError("SECRET SQL")
        ):
            with self.assertLogs("auditlog.service", level="ERROR") as logs:
                self.assertEqual(self.client.get("/").status_code, 200)
        self.assertNotIn("SECRET", str(logs.output))
        self.assertEqual(User.objects.count(), 1)

    def test_model_and_queryset_are_append_only(self):
        event = self.event()
        for mutation in (
            event.save,
            event.delete,
            lambda: AuditEvent.objects.update(result="error"),
            AuditEvent.objects.all().delete,
        ):
            with self.assertRaises(TypeError):
                mutation()

    @override_settings(AUDIT_LOG_RETENTION_DAYS=365)
    def test_pruning_strict_cutoff_preserves_recent_rows_and_is_idempotent(self):
        now = timezone.now()
        cutoff = now - timedelta(days=365)
        self.event(created_at=cutoff - timedelta(microseconds=1))
        kept = self.event(created_at=cutoff)
        newer = self.event(created_at=now)
        output = StringIO()
        with patch("auditlog.management.commands.prune_audit_logs.timezone.now", return_value=now):
            call_command("prune_audit_logs", stdout=output)
            call_command("prune_audit_logs", stdout=output)
        self.assertEqual(set(AuditEvent.objects.values_list("pk", flat=True)), {kept.pk, newer.pk})
        self.assertIn("Deleted 1", output.getvalue())
        self.assertIn("Deleted 0", output.getvalue())

    def test_threshold_endpoint_is_narrow_staff_write_only_and_csrf_protected(self):
        self.membership.return_value = Membership(True, ("300",))
        payload = {
            "event_type": EventType.THRESHOLD_CHANGED,
            "table": "normal-diamonds",
            "old_threshold": 1000,
            "new_threshold": 2500,
        }
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")
        url = "/audit/client-event/"
        self.assertEqual(
            client.post(url, payload, content_type="application/json").status_code, 403
        )
        client.get("/")
        token = client.cookies["csrftoken"].value
        response = client.post(
            url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(response.status_code, 204)
        event = AuditEvent.objects.get(event_type=EventType.THRESHOLD_CHANGED)
        self.assertEqual(event.actor_discord_id, self.user.discord_id)
        self.assertEqual(event.metadata_json["new_threshold"], 2500)
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.get("/audit-log/").status_code, 403)
        for data in (
            [],
            {**payload, "metadata": "anything"},
            {**payload, "table": "unknown"},
            {**payload, "event_type": "arbitrary"},
            {**payload, "new_threshold": "2500"},
            {**payload, "old_threshold": True},
            {**payload, "new_threshold": 1000},
        ):
            self.assertEqual(
                client.post(
                    url, data, content_type="application/json", HTTP_X_CSRFTOKEN=token
                ).status_code,
                400,
            )
        self.assertEqual(
            AuditEvent.objects.filter(event_type=EventType.THRESHOLD_CHANGED).count(), 1
        )
        with patch("auditlog.views.record", return_value=False):
            self.assertEqual(
                client.post(
                    url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=token
                ).status_code,
                503,
            )


class AuthenticationAuditTests(TestCase):
    def login_callback(self, membership=None, error=None):
        membership = membership if membership is not None else Membership(True, ("200",))
        state = parse_qs(urlsplit(self.client.post("/auth/login/").url).query)["state"][0]
        with (
            patch(
                "accounts.views.discord.fetch_profile",
                return_value={
                    "discord_id": "123456789",
                    "username": "staff",
                    "display_name": "Team",
                    "avatar": "",
                },
                side_effect=error,
            ),
            patch("accounts.permissions.fetch_membership", return_value=membership),
        ):
            return self.client.get("/auth/callback/", {"state": state, "code": "PRIVATE"})

    def test_success_and_logout(self):
        self.assertEqual(self.login_callback().status_code, 302)
        event = AuditEvent.objects.get()
        self.assertEqual(event.event_type, EventType.AUTH_SUCCEEDED)
        self.assertEqual(event.metadata_json, {"authorization_source": "discord_role"})
        self.client.post("/auth/logout/")
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=EventType.LOGOUT, actor_discord_id="123456789"
            ).exists()
        )

    def test_missing_role_non_member_and_oauth_failure(self):
        for membership, reason in (
            (Membership(True, ()), "missing_required_role"),
            (Membership(False), "not_in_guild"),
        ):
            self.assertEqual(self.login_callback(membership).status_code, 403)
            self.assertEqual(AuditEvent.objects.first().metadata_json["reason"], reason)
        self.assertEqual(self.login_callback(error=DiscordUnavailable()).status_code, 503)
        event = AuditEvent.objects.first()
        self.assertIsNone(event.actor_discord_id)
        self.assertEqual(
            (event.result, event.metadata_json["reason"]), (Result.ERROR, "oauth_error")
        )
        self.assertNotIn("PRIVATE", str(event.__dict__))

    def test_invalid_state_is_unknown_actor_even_when_old_session_exists(self):
        user = User.objects.create_user("123456789")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        self.client.get("/auth/callback/", {"state": "SECRET", "code": "SECRET"})
        event = AuditEvent.objects.get()
        self.assertIsNone(event.actor_discord_id)
        self.assertEqual(event.request_query, {})
        self.assertEqual(event.metadata_json, {"reason": "invalid_state"})

    def test_database_audit_failure_does_not_break_oauth(self):
        with (
            patch(
                "auditlog.service.AuditEvent.objects.create", side_effect=DatabaseError("secret")
            ),
            self.assertLogs("auditlog.service"),
        ):
            self.assertEqual(self.login_callback().status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
