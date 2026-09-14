from accounts.permissions import PORTAL_CONFIGURE


def navigation(request):
    permissions = getattr(request, "portal_permissions", ())
    return {
        "can_configure": PORTAL_CONFIGURE in permissions,
        "can_view_analytics": "minecraft.analytics" in permissions,
    }
