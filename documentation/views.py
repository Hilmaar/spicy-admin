from django.http import Http404
from django.shortcuts import render

from accounts.permissions import PORTAL_ACCESS, permission_required
from auditlog.events import EventType
from auditlog.service import record

from .content import load_page


@permission_required(PORTAL_ACCESS)
def page(request, slug):
    try:
        context = load_page(slug)
    except (KeyError, FileNotFoundError):
        raise Http404 from None
    if request.method == "GET" and slug == "code-of-conduct":
        record(request, EventType.CODE_OF_CONDUCT)
    return render(request, "documentation/page.html", context)
