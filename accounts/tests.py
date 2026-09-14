import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from django.conf import settings
from django.contrib.auth import authenticate
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .discord import DiscordUnavailable, Membership, fetch_membership, fetch_profile
from .models import GuildAuthorization, User
from .permissions import PORTAL_ACCESS, PORTAL_CONFIGURE, permissions_for_roles


class PermissionMappingTests(SimpleTestCase):
    def test_role_hierarchy(self):
        self.assertEqual(
            permissions_for_roles(["200"]),
            {
                PORTAL_ACCESS,
                PORTAL_CONFIGURE,
                "minecraft.analytics",
                "minecraft.punishments",
            },
        )
        self.assertEqual(
            permissions_for_roles(["300"]),
            {
                PORTAL_ACCESS,
                "minecraft.analytics",
                "minecraft.punishments",
            },
        )
        for roles in (["400"], [], ["Minecraft Overlord"], ["999"]):
            with self.subTest(roles=roles):
                self.assertEqual(permissions_for_roles(roles), set())

    def test_membership_is_required_even_for_admin(self):
        self.assertEqual(permissions_for_roles(["200"], is_member=False), set())

    @override_settings(DISCORD_ADMIN_ROLE_ID="", DISCORD_OVERLORD_ROLE_ID="")
    def test_empty_configuration_never_grants_access(self):
        self.assertEqual(permissions_for_roles([""]), set())


class AuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "123456789", username="Staff", display_name="Staff User"
        )
        self.membership = patch("accounts.permissions.fetch_membership")
        self.fetch = self.membership.start()
        self.fetch.return_value = Membership(True, ("200",))
        self.addCleanup(self.membership.stop)

    def sign_in(self):
        self.client.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")

    def expire(self):
        GuildAuthorization.objects.filter(user=self.user).update(
            checked_at=timezone.now() - timedelta(seconds=61),
        )

    def test_anonymous_blocked_from_every_protected_page(self):
        for path in ("/", "/docs/code-of-conduct/", "/docs/admin-cheat-sheet/", "/diagnostics/"):
            with self.subTest(path=path):
                self.assertRedirects(self.client.get(path), "/auth/login/")
        self.fetch.assert_not_called()

    def test_admin_allowed_and_profile_shown(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertContains(response, "Staff User")
        self.assertContains(response, self.user.avatar_url)
        self.assertContains(response, 'href="/diagnostics/"')
        self.assertEqual(self.client.get("/diagnostics/").status_code, 200)

    def test_overlord_allowed_without_configuration_permission(self):
        self.fetch.return_value = Membership(True, ("300",))
        self.sign_in()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/diagnostics/"')
        self.assertEqual(self.client.get("/diagnostics/").status_code, 403)

    def test_patron_and_ordinary_member_denied(self):
        self.sign_in()
        for roles in (("400",), ()):
            with self.subTest(roles=roles):
                GuildAuthorization.objects.all().delete()
                self.fetch.return_value = Membership(True, roles)
                self.assertEqual(self.client.get("/").status_code, 403)

    def test_recent_verification_reused_across_sessions(self):
        self.sign_in()
        self.client.get("/")
        other = Client()
        other.force_login(self.user, backend="accounts.backends.DiscordSessionBackend")
        self.assertEqual(other.get("/docs/code-of-conduct/").status_code, 200)
        self.fetch.assert_called_once_with(self.user.discord_id)

    def test_role_removal_denies_after_cache_expiry(self):
        self.sign_in()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.fetch.return_value = Membership(True, ())
        self.assertEqual(self.client.get("/").status_code, 200)
        self.expire()
        self.assertEqual(self.client.get("/").status_code, 403)
        self.assertEqual(self.client.get("/docs/code-of-conduct/").status_code, 403)

    def test_guild_removal_denies_after_cache_expiry(self):
        self.sign_in()
        self.client.get("/")
        self.expire()
        self.fetch.return_value = Membership(False)
        self.assertEqual(self.client.get("/").status_code, 403)

    def test_admin_downgrade_restricts_diagnostics_after_revalidation(self):
        self.sign_in()
        self.client.get("/diagnostics/")
        self.expire()
        self.fetch.return_value = Membership(True, ("300",))
        self.assertEqual(self.client.get("/diagnostics/").status_code, 403)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_api_failure_fails_closed_and_recovers(self):
        self.sign_in()
        self.client.get("/")
        self.expire()
        self.fetch.side_effect = DiscordUnavailable()
        response = self.client.get("/")
        self.assertContains(response, "Access verification unavailable", status_code=503)
        self.assertEqual(self.client.get("/diagnostics/").status_code, 503)
        self.assertEqual(self.fetch.call_count, 2)
        self.expire()
        self.fetch.side_effect = None
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_guild_config_change_forces_revalidation(self):
        self.sign_in()
        self.client.get("/")
        with override_settings(DISCORD_GUILD_ID="999"):
            self.fetch.return_value = Membership(False)
            self.assertEqual(self.client.get("/").status_code, 403)
        self.assertEqual(self.fetch.call_count, 2)

    def test_permissions_recomputed_if_configured_role_changes(self):
        self.sign_in()
        self.client.get("/")
        with override_settings(DISCORD_ADMIN_ROLE_ID="999"):
            self.assertEqual(self.client.get("/").status_code, 403)

    def test_exact_cache_boundary_and_future_timestamp_refresh(self):
        self.sign_in()
        now = timezone.now()
        for checked_at in (now - timedelta(seconds=45), now + timedelta(seconds=1)):
            with self.subTest(checked_at=checked_at):
                GuildAuthorization.objects.update_or_create(
                    user=self.user,
                    defaults={
                        "guild_id": "100",
                        "roles": ["200"],
                        "is_member": True,
                        "checked_at": checked_at,
                    },
                )
                self.fetch.return_value = Membership(False)
                with patch("accounts.permissions.timezone.now", return_value=now):
                    self.assertEqual(self.client.get("/").status_code, 403)

    def test_no_local_password_authentication(self):
        self.assertFalse(self.user.has_usable_password())
        self.user.set_password("even-if-a-password-is-set")
        self.user.save()
        self.assertIsNone(
            authenticate(discord_id=self.user.discord_id, password="even-if-a-password-is-set")
        )

    def test_inactive_session_is_not_restored(self):
        self.sign_in()
        self.user.is_active = False
        self.user.save()
        self.assertRedirects(self.client.get("/"), "/auth/login/")

    def test_private_response_security_headers(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")


class OAuthTests(TestCase):
    def setUp(self):
        self.profile = {
            "discord_id": "123456789",
            "username": "staff",
            "display_name": "Team member",
            "avatar": "a" * 32,
        }

    def begin(self):
        response = self.client.post("/auth/login/")
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.url).query)
        self.assertEqual(query["scope"], ["identify"])
        self.assertEqual(query["redirect_uri"], [settings.DISCORD_REDIRECT_URI])
        return query["state"][0]

    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("200",)))
    @patch("accounts.views.discord.fetch_profile")
    def test_complete_flow_and_replay_rejected(self, profile, membership):
        profile.return_value = self.profile
        state = self.begin()
        response = self.client.get(
            "/auth/callback/",
            {"state": state, "code": "test-code", "next": "https://evil.example/"},
        )
        self.assertRedirects(response, "/")
        user = User.objects.get()
        self.assertEqual(user.display_name, "Team member")
        self.assertIsNotNone(user.last_login)
        self.assertFalse(user.has_usable_password())
        self.assertNotIn("oauth_state", self.client.session)
        self.assertNotIn("access_token", self.client.session)
        self.assertEqual(
            self.client.get(
                "/auth/callback/",
                {
                    "state": state,
                    "code": "test-code",
                },
            ).status_code,
            400,
        )
        profile.assert_called_once_with("test-code")

    @patch("accounts.views.discord.fetch_profile")
    def test_bad_state_never_calls_discord(self, profile):
        for query in (
            {},
            {"code": "test"},
            {"state": "wrong", "code": "test"},
            {"state": "☃", "code": "test"},
        ):
            with self.subTest(query=query):
                self.begin()
                self.assertEqual(self.client.get("/auth/callback/", query).status_code, 400)
        profile.assert_not_called()

    def test_callback_suppresses_referrers(self):
        response = self.client.get("/auth/callback/")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_expired_state(self):
        state = self.begin()
        session = self.client.session
        session["oauth_state"] = {"value": state, "created": time.time() - 601}
        session.save()
        self.assertEqual(
            self.client.get(
                "/auth/callback/",
                {
                    "state": state,
                    "code": "test",
                },
            ).status_code,
            400,
        )

    def test_cancelled_and_incomplete_callback(self):
        for extra in ({"error": "access_denied"}, {}):
            with self.subTest(extra=extra):
                state = self.begin()
                self.assertEqual(
                    self.client.get(
                        "/auth/callback/",
                        {
                            "state": state,
                            **extra,
                        },
                    ).status_code,
                    400,
                )

    @patch("accounts.views.discord.fetch_profile", side_effect=DiscordUnavailable("Try again."))
    def test_api_failure_creates_no_session(self, profile):
        state = self.begin()
        self.assertEqual(
            self.client.get(
                "/auth/callback/",
                {
                    "state": state,
                    "code": "test",
                },
            ).status_code,
            503,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("400",)))
    @patch("accounts.views.discord.fetch_profile")
    def test_no_session_for_unprivileged_profile(self, profile, membership):
        profile.return_value = self.profile
        state = self.begin()
        self.assertEqual(
            self.client.get(
                "/auth/callback/",
                {
                    "state": state,
                    "code": "test",
                },
            ).status_code,
            403,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(DISCORD_CLIENT_ID="")
    def test_missing_configuration(self):
        self.assertContains(self.client.get("/auth/login/"), "awaiting configuration")
        self.assertEqual(self.client.post("/auth/login/").status_code, 503)

    def test_login_and_logout_require_csrf_and_logout_requires_post(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post("/auth/login/").status_code, 403)
        self.assertEqual(csrf_client.post("/auth/logout/").status_code, 403)
        self.assertEqual(self.client.get("/auth/logout/").status_code, 405)
        user = User.objects.create_user("123", username="staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        self.assertRedirects(self.client.post("/auth/logout/"), "/auth/login/")
        self.assertNotIn("_auth_user_id", self.client.session)


class DiscordClientTests(SimpleTestCase):
    def transport(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        patched = patch("accounts.discord.httpx.Client", return_value=client)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_bot_member_query(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v10/guilds/100/members/123")
            self.assertEqual(request.headers["Authorization"], "Bot test-only-bot-token")
            return httpx.Response(200, json={"roles": ["200"]})

        self.transport(handler)
        self.assertEqual(fetch_membership("123"), Membership(True, ("200",)))

    def test_missing_guild_member(self):
        self.transport(lambda request: httpx.Response(404))
        self.assertEqual(fetch_membership("123"), Membership(False))

    def test_rate_limit_and_error_bodies_not_exposed(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                with patch("accounts.discord.httpx.Client") as client:
                    client.return_value.__enter__.return_value.request.return_value = (
                        httpx.Response(
                            status,
                            text="secret-token database-password",
                        )
                    )
                    with self.assertRaises(DiscordUnavailable) as caught:
                        fetch_membership("123")
                    self.assertNotIn("secret-token", str(caught.exception))

    def test_malformed_roles_rejected(self):
        self.transport(lambda request: httpx.Response(200, json={"roles": "200"}))
        with self.assertRaises(DiscordUnavailable):
            fetch_membership("123")

    def test_invalid_json_and_timeout(self):
        for result in (httpx.Response(200, text="invalid"), httpx.ConnectTimeout("secret-host")):
            with self.subTest(result=result):
                with patch("accounts.discord.httpx.Client") as client:
                    request = client.return_value.__enter__.return_value.request
                    if isinstance(result, Exception):
                        request.side_effect = result
                    else:
                        request.return_value = result
                    with self.assertRaises(DiscordUnavailable):
                        fetch_membership("123")

    @patch("accounts.discord._request")
    def test_profile_token_exchange_and_validation(self, request):
        request.side_effect = [
            {"access_token": "temporary-token"},
            {
                "id": "123",
                "username": "Staff",
                "global_name": "Display",
                "avatar": None,
            },
        ]
        profile = fetch_profile("test-code")
        self.assertEqual(profile["display_name"], "Display")
        self.assertNotIn("access_token", profile)
        self.assertEqual(
            request.call_args_list[0].kwargs["data"]["grant_type"], "authorization_code"
        )
        request.side_effect = [
            {"access_token": "temporary-token"},
            {
                "id": "123",
                "username": "Staff",
                "avatar": "../evil",
            },
        ]
        with self.assertRaises(DiscordUnavailable):
            fetch_profile("test-code")
