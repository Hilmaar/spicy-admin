from django.shortcuts import render

from accounts.permissions import PORTAL_ACCESS, permission_required
from auditlog.events import EventType
from auditlog.service import record
from coreprotect.services import connection_status


@permission_required(PORTAL_ACCESS)
def dashboard(request):
    if request.method == "GET":
        record(request, EventType.DASHBOARD)
    return render(request, "portal/dashboard.html", {"coreprotect": connection_status()})
