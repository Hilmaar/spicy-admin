import secrets
import time

from django.contrib.auth import login as session_login
from django.contrib.auth import logout as session_logout
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from auditlog.events import EventType, Result
from auditlog.service import record

from . import discord
from .models import GuildAuthorization, User
from .permissions import PORTAL_ACCESS, authorization_for


@require_http_methods(["GET", "POST"])
def login(request):
    if request.method == "GET":
        return render(request, "accounts/login.html", {"discord_configured": discord.configured()})
    if not discord.configured():
        return render(
            request,
            "accounts/access_error.html",
            {
                "title": "Login is not configured",
                "message": "A portal owner needs to finish the Discord configuration.",
            },
            status=503,
        )
    request.session.cycle_key()
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = {"value": state, "created": time.time()}
    return redirect(discord.authorization_url(state))


@require_GET
@sensitive_variables()
def callback(request):
    pending = request.session.pop("oauth_state", None)
    supplied = request.GET.get("state", "")
    if not (
        pending
        and supplied
        and len(supplied) <= 128
        and secrets.compare_digest(pending["value"].encode(), supplied.encode())
        and 0 <= time.time() - pending["created"] <= 600
    ):
        record(
            request,
            EventType.AUTH_DENIED,
            result=Result.DENIED,
            actor=None,
            metadata={"reason": "invalid_state"},
        )
        return render(
            request,
            "accounts/access_error.html",
            {
                "title": "Login could not be verified",
                "message": "The login link has expired or is invalid. Start a new Discord login.",
            },
            status=400,
        )
    if request.GET.get("error"):
        record(
            request,
            EventType.AUTH_DENIED,
            result=Result.DENIED,
            actor=None,
            metadata={"reason": "oauth_error"},
        )
        return render(
            request,
            "accounts/access_error.html",
            {
                "title": "Login cancelled",
                "message": "Discord login was not completed. You can try again.",
            },
            status=400,
        )
    code = request.GET.get("code", "")
    if not code or len(code) > 2048:
        record(
            request,
            EventType.AUTH_DENIED,
            result=Result.DENIED,
            actor=None,
            metadata={"reason": "oauth_error"},
        )
        return render(
            request,
            "accounts/access_error.html",
            {
                "title": "Incomplete login",
                "message": "Start a new Discord login to continue.",
            },
            status=400,
        )
    user = None
    try:
        profile = discord.fetch_profile(code)
        with transaction.atomic():
            user, _ = User.objects.get_or_create(discord_id=profile["discord_id"])
            user = User.objects.select_for_update().get(pk=user.pk)
            if not user.is_active:
                record(
                    request,
                    EventType.AUTH_DENIED,
                    result=Result.DENIED,
                    actor=user,
                    metadata={"reason": "inactive_account"},
                )
                return render(
                    request,
                    "accounts/access_error.html",
                    {
                        "title": "Access restricted",
                        "message": "This portal account is inactive.",
                    },
                    status=403,
                )
            for field in ("username", "display_name", "avatar"):
                setattr(user, field, profile[field])
            user.set_unusable_password()
            user.save()
            GuildAuthorization.objects.filter(user=user).delete()
        if PORTAL_ACCESS not in authorization_for(user):
            state = GuildAuthorization.objects.get(user=user)
            record(
                request,
                EventType.AUTH_DENIED,
                result=Result.DENIED,
                actor=user,
                metadata={"reason": "missing_required_role" if state.is_member else "not_in_guild"},
            )
            return render(
                request,
                "accounts/access_error.html",
                {
                    "title": "Access restricted",
                    "message": "Join the configured spicy.is Discord server and hold the Admin or "
                    "Minecraft Overlord role to enter this portal.",
                },
                status=403,
            )
    except discord.DiscordUnavailable as exc:
        record(
            request,
            EventType.AUTH_DENIED,
            result=Result.ERROR,
            actor=user,
            metadata={"reason": "oauth_error"},
        )
        return render(
            request,
            "accounts/access_error.html",
            {
                "title": "Discord login unavailable",
                "message": str(exc),
            },
            status=503,
        )
    session_login(request, user, backend="accounts.backends.DiscordSessionBackend")
    record(request, EventType.AUTH_SUCCEEDED, actor=user)
    # Always use our fixed destination; never trust a callback/next URL supplied by the browser.
    return redirect("portal:dashboard")


@require_POST
def logout(request):
    if request.user.is_authenticated:
        record(request, EventType.LOGOUT)
    session_logout(request)
    return redirect("accounts:login")
