from django.shortcuts import render

from accounts.permissions import PORTAL_ACCESS, permission_required
from coreprotect.services import connection_status


@permission_required(PORTAL_ACCESS)
def dashboard(request):
    return render(request, "portal/dashboard.html", {"coreprotect": connection_status()})
