from django.shortcuts import render

from accounts.permissions import PORTAL_CONFIGURE, permission_required

from .services import diagnostics


@permission_required(PORTAL_CONFIGURE)
def index(request):
    return render(request, "coreprotect/diagnostics.html", {"diagnostic": diagnostics()})
