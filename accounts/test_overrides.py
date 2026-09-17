import os
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from auditlog.events import EventType
from auditlog.models import AuditEvent

from .configuration import parse_access_override_ids
from .discord import DiscordUnavailable, Membership
from .models import GuildAuthorization, User
from .permissions import MINECRAFT_PERMISSIONS, authorization_for


class OverrideConfigurationTests(SimpleTestCase):
    def test_empty_configuration(self):
        for value in ("", " , , "):
            self.assertEqual(parse_access_override_ids(value), frozenset())

    def test_one_id(self):
        self.assertEqual(parse_access_override_ids("123456789012345678"), {"123456789012345678"})

    def test_multiple_ids_whitespace_empty_entries_and_duplicates(self):
        self.assertEqual(
            parse_access_override_ids(
                " 123456789012345678, ,987654321098765432,, 123456789012345678 "
            ),
            {"123456789012345678", "987654321098765432"},
        )

    def test_invalid_values_fail_configuration_without_echoing_input(self):
        for value in (
            "username",
            "123abc",
            "-12",
            "+12",
            "0",
            "0123",
            "１２３",
            "1 23",
            str(2**64),
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesMessage(ImproperlyConfigured, "DISCORD_ACCESS_OVERRIDE_USER_IDS"),
            ):
                parse_access_override_ids("123456789012345678," + value)

    def test_invalid_environment_rejected_during_settings_startup(self):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DISCORD_ACCESS_OVERRIDE_USER_IDS": "invalid-configured-identity",
        }
        result = subprocess.run(
            [sys.executable, "-c", "from django.conf import settings; settings.INSTALLED_APPS"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("DISCORD_ACCESS_OVERRIDE_USER_IDS", result.stderr)
        self.assertNotIn("invalid-configured-identity", result.stderr)


@override_settings(
    DISCORD_ACCESS_OVERRIDE_USER_IDS=frozenset({"123456789012345678", "987654321098765432"})
)
class OverrideAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("123456789012345678", username="Staff")
        mock = patch("accounts.permissions.fetch_membership", return_value=Membership(False))
        self.membership = mock.start()
        self.addCleanup(mock.stop)

    def sign_in(self):
        self.client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")

    def test_non_member_and_member_without_role_receive_only_staff_permissions(self):
        for membership in (Membership(False), Membership(True, ()), Membership(True, ("400",))):
            with self.subTest(membership=membership):
                GuildAuthorization.objects.all().delete()
                self.membership.return_value = membership
                self.assertEqual(authorization_for(self.user), MINECRAFT_PERMISSIONS)
                self.assertNotIn("portal.configure", authorization_for(self.user))
                self.assertNotIn("portal.audit_log", authorization_for(self.user))

    def test_roles_combine_without_duplicate_permissions(self):
        for role, extra in (("200", {"portal.configure", "portal.audit_log"}), ("300", set())):
            with self.subTest(role=role):
                GuildAuthorization.objects.all().delete()
                self.membership.return_value = Membership(True, (role,))
                self.assertEqual(authorization_for(self.user), MINECRAFT_PERMISSIONS | extra)
                self.assertEqual(self.user._portal_authorization_source, "discord_role")

    def test_removal_takes_effect_at_next_authorization_without_waiting_for_role_cache(self):
        self.sign_in()
        self.assertEqual(self.client.get("/").status_code, 200)
        with override_settings(DISCORD_ACCESS_OVERRIDE_USER_IDS=frozenset()):
            self.assertEqual(self.client.get("/").status_code, 403)
        self.membership.assert_called_once()

    def test_override_survives_role_api_outage_but_removal_fails_closed(self):
        self.membership.side_effect = DiscordUnavailable()
        self.assertEqual(authorization_for(self.user), MINECRAFT_PERMISSIONS)
        with override_settings(DISCORD_ACCESS_OVERRIDE_USER_IDS=frozenset()):
            with self.assertRaises(DiscordUnavailable):
                authorization_for(self.user)

    def test_anonymous_inactive_and_non_allowlisted_users_are_not_authorized(self):
        self.assertEqual(authorization_for(AnonymousUser()), set())
        self.assertRedirects(self.client.get("/"), "/auth/login/")
        self.user.is_active = False
        self.assertEqual(authorization_for(self.user), set())
        stranger = User.objects.create_user("555555555555555555", username=self.user.username)
        self.assertEqual(authorization_for(stranger), set())

    def test_override_has_no_audit_read_or_configuration_access(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertNotContains(response, 'href="/audit-log/"')
        self.assertNotContains(response, "987654321098765432")
        self.assertEqual(self.client.get("/diagnostics/").status_code, 403)
        self.assertEqual(self.client.get("/audit-log/").status_code, 403)
        event = AuditEvent.objects.get(event_type=EventType.DASHBOARD)
        for suffix in ("", "?format=json"):
            self.assertEqual(self.client.get(f"/audit-log/{event.pk}/{suffix}").status_code, 403)

    def test_normal_oauth_non_member_override_success_is_audited_without_denial_or_list(self):
        profile = dict(
            discord_id=self.user.discord_id, username="Staff", display_name="Preview", avatar=""
        )
        state = parse_qs(urlsplit(self.client.post("/auth/login/").url).query)["state"][0]
        with patch("accounts.views.discord.fetch_profile", return_value=profile) as fetch:
            response = self.client.get("/auth/callback/", {"state": state, "code": "private-code"})
        self.assertEqual(response.status_code, 302)
        fetch.assert_called_once_with("private-code")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertFalse(AuditEvent.objects.filter(event_type=EventType.AUTH_DENIED).exists())
        event = AuditEvent.objects.get(event_type=EventType.AUTH_SUCCEEDED)
        self.assertEqual(event.actor_discord_id, self.user.discord_id)
        self.assertEqual(event.metadata_json, {"authorization_source": "user_override"})
        self.assertEqual(event.request_query, {})
        self.assertNotIn("987654321098765432", str(event.__dict__))
        self.assertNotIn("private-code", str(event.__dict__))

    def test_allowlist_does_not_bypass_oauth_state_validation(self):
        with patch("accounts.views.discord.fetch_profile") as fetch:
            response = self.client.get("/auth/callback/", {"state": "fake", "code": "fake"})
        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()
        self.assertNotIn("_auth_user_id", self.client.session)
