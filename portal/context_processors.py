from accounts.permissions import PORTAL_CONFIGURE


def navigation(request):
    return {"can_configure": PORTAL_CONFIGURE in getattr(request, "portal_permissions", ())}
