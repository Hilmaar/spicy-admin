from django.http import Http404
from django.shortcuts import render

from accounts.permissions import PORTAL_ACCESS, permission_required

from .content import load_page


@permission_required(PORTAL_ACCESS)
def page(request, slug):
    try:
        context = load_page(slug)
    except (KeyError, FileNotFoundError):
        raise Http404 from None
    return render(request, "documentation/page.html", context)
