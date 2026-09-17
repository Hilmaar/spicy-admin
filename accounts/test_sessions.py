"""Multi-device OAuth regression and session/authorization separation."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .discord import DiscordUnavailable, Membership
from .models import GuildAuthorization, User


class OAuthSessionContinuityTests(TestCase):
    def oauth(self, client):
        state = parse_qs(urlsplit(client.post("/auth/login/").url).query)["state"][0]
        response = client.get("/auth/callback/", {"state": state, "code": "test-only-code"})
        self.assertEqual(response.status_code, 302)

    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("200",)))
    @patch(
        "accounts.views.discord.fetch_profile",
        return_value={
            "discord_id": "123456789",
            "username": "Staff",
            "display_name": "Staff",
            "avatar": "",
        },
    )
    def test_second_device_oauth_preserves_first_devices_valid_session(self, profile, membership):
        first, second = Client(), Client()
        self.oauth(first)
        original_key = first.session.session_key
        self.assertEqual(first.get("/").status_code, 200)
        self.oauth(second)
        self.assertEqual(second.get("/").status_code, 200)
        self.assertEqual(first.get("/").status_code, 200)
        self.assertEqual(first.session.session_key, original_key)
        self.assertFalse(User.objects.get().has_usable_password())

    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("200",)))
    def test_navigation_role_refresh_revocation_and_outage_do_not_rotate_or_clear_session(
        self, membership
    ):
        user = User.objects.create_user("123456789", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        key = self.client.session.session_key
        original = dict(self.client.session)
        for path in ("/", "/docs/code-of-conduct/", "/audit-log/"):
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(self.client.session.session_key, key)
        GuildAuthorization.objects.update(checked_at=timezone.now() - timedelta(seconds=61))
        membership.return_value = Membership(True, ())
        self.assertEqual(self.client.get("/").status_code, 403)
        GuildAuthorization.objects.all().delete()
        membership.side_effect = DiscordUnavailable()
        self.assertEqual(self.client.get("/").status_code, 503)
        self.assertEqual(self.client.session.session_key, key)
        self.assertEqual(dict(self.client.session), original)
        self.assertTrue(Session.objects.filter(session_key=key).exists())

    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("200",)))
    def test_profile_edits_preserve_sessions_but_real_auth_hash_changes_still_revoke(
        self, membership
    ):
        user = User.objects.create_user("123456789", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        user.username = "Renamed"
        user.display_name = "New display"
        user.save()
        self.assertEqual(self.client.get("/").status_code, 200)
        user.set_unusable_password()  # Explicit credential reset must still revoke sessions.
        user.save()
        self.assertRedirects(self.client.get("/"), "/auth/login/")

    def test_secret_key_change_without_fallback_invalidates_session(self):
        user = User.objects.create_user("123456789", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        with override_settings(SECRET_KEY="different-test-only-key", SECRET_KEY_FALLBACKS=[]):
            self.assertRedirects(self.client.get("/"), "/auth/login/")
