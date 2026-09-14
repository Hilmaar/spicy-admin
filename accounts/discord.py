import re
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

API = "https://discord.com/api/v10"


class DiscordUnavailable(Exception):
    """Safe public error; never include response bodies, credentials, or request URLs."""


@dataclass(frozen=True)
class Membership:
    is_member: bool
    roles: tuple[str, ...] = ()


def configured():
    identifiers = [
        settings.DISCORD_CLIENT_ID,
        settings.DISCORD_GUILD_ID,
        settings.DISCORD_ADMIN_ROLE_ID,
        settings.DISCORD_OVERLORD_ROLE_ID,
    ]
    return all(re.fullmatch(r"[0-9]{1,20}", value) for value in identifiers) and all(
        [
            settings.DISCORD_CLIENT_SECRET,
            settings.DISCORD_BOT_TOKEN,
            settings.DISCORD_REDIRECT_URI,
        ]
    )


def authorization_url(state):
    return "https://discord.com/oauth2/authorize?" + urlencode(
        {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
            "state": state,
        }
    )


@sensitive_variables()
def _request(method, path, *, missing_member=False, **kwargs):
    try:
        with httpx.Client(timeout=httpx.Timeout(5, connect=3), follow_redirects=False) as client:
            response = client.request(method, API + path, **kwargs)
        if missing_member and response.status_code == 404:
            return None
        if response.status_code != 200:
            raise DiscordUnavailable("Discord could not verify access. Please try again shortly.")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (httpx.HTTPError, ValueError):
        raise DiscordUnavailable(
            "Discord could not verify access. Please try again shortly."
        ) from None


@sensitive_variables()
def fetch_profile(code):
    token = _request(
        "POST",
        "/oauth2/token",
        data={
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
        },
    )
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise DiscordUnavailable("Discord returned an incomplete login response.")
    # The token lives only in this call; revalidation uses the bot's guild-member endpoint.
    profile = _request("GET", "/users/@me", headers={"Authorization": f"Bearer {access_token}"})
    discord_id = profile.get("id", "")
    username = profile.get("username", "")
    avatar = profile.get("avatar") or ""
    display_name = profile.get("global_name") or username
    if not (
        isinstance(discord_id, str)
        and re.fullmatch(r"[0-9]{1,20}", discord_id)
        and isinstance(username, str)
        and 0 < len(username) <= 80
        and isinstance(display_name, str)
        and len(display_name) <= 80
        and isinstance(avatar, str)
        and re.fullmatch(r"(?:a_)?[a-f0-9]{32}|", avatar)
    ):
        raise DiscordUnavailable("Discord returned an incomplete profile.")
    return {
        "discord_id": discord_id,
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
    }


def fetch_membership(discord_id):
    if not configured():
        raise DiscordUnavailable("Discord access has not been configured. Contact a portal owner.")
    result = _request(
        "GET",
        f"/guilds/{settings.DISCORD_GUILD_ID}/members/{discord_id}",
        missing_member=True,
        headers={"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"},
    )
    if result is None:
        return Membership(False)
    roles = result.get("roles")
    if not isinstance(roles, list) or any(
        not isinstance(role, str) or not re.fullmatch(r"[0-9]{1,20}", role) for role in roles
    ):
        raise DiscordUnavailable("Discord returned incomplete membership information.")
    return Membership(True, tuple(roles))
