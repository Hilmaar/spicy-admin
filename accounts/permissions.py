from functools import wraps

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .discord import DiscordUnavailable, fetch_membership
from .models import GuildAuthorization, User

PORTAL_ACCESS = "portal.access"
PORTAL_CONFIGURE = "portal.configure"
MINECRAFT_PERMISSIONS = {PORTAL_ACCESS, "minecraft.analytics", "minecraft.punishments"}


def permissions_for_roles(roles, is_member=True):
    if not is_member:
        return frozenset()
    roles = set(roles)
    permissions = set()
    if settings.DISCORD_ADMIN_ROLE_ID and settings.DISCORD_ADMIN_ROLE_ID in roles:
        permissions.update(MINECRAFT_PERMISSIONS | {PORTAL_CONFIGURE})
    if settings.DISCORD_OVERLORD_ROLE_ID and settings.DISCORD_OVERLORD_ROLE_ID in roles:
        permissions.update(MINECRAFT_PERMISSIONS)
    # Patron and guild membership deliberately grant no Phase 1 permissions.
    return frozenset(permissions)


def _fresh(state):
    if not state or state.guild_id != settings.DISCORD_GUILD_ID:
        return False
    age = (timezone.now() - state.checked_at).total_seconds()
    return 0 <= age < settings.DISCORD_ROLE_CACHE_SECONDS


def authorization_for(user):
    state = GuildAuthorization.objects.filter(user=user).first()
    if not _fresh(state):
        # Serialize refreshes for a user across workers. Check again after taking the lock.
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            state = GuildAuthorization.objects.filter(user=user).first()
            if not _fresh(state):
                checked_at = timezone.now()
                try:
                    membership = fetch_membership(user.discord_id)
                    values = {
                        "roles": list(membership.roles),
                        "is_member": membership.is_member,
                        "unavailable": False,
                    }
                except DiscordUnavailable:
                    # Cache a denial briefly, never reuse stale permissions during an outage.
                    values = {"roles": [], "is_member": False, "unavailable": True}
                state, _ = GuildAuthorization.objects.update_or_create(
                    user=user,
                    defaults={
                        **values,
                        "checked_at": checked_at,
                        "guild_id": settings.DISCORD_GUILD_ID,
                    },
                )
    if state.unavailable:
        raise DiscordUnavailable("Discord could not verify access. Please try again shortly.")
    return permissions_for_roles(state.roles, state.is_member)


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("accounts:login")
            try:
                request.portal_permissions = authorization_for(request.user)
            except DiscordUnavailable as exc:
                return render(
                    request,
                    "accounts/access_error.html",
                    {
                        "title": "Access verification unavailable",
                        "message": str(exc),
                    },
                    status=503,
                )
            if permission not in request.portal_permissions:
                return render(
                    request,
                    "accounts/access_error.html",
                    {
                        "title": "Access restricted",
                        "message": "Your current Discord membership and roles do not allow "
                        "this page. "
                        "Contact a spicy.is owner if you need access.",
                    },
                    status=403,
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
