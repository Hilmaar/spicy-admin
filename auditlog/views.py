import json
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.permissions import PORTAL_AUDIT_LOG, permission_required
from analytics.ore_config import SAMPLE_OPTIONS

from .events import EventType
from .forms import AuditFiltersForm
from .models import AuditEvent
from .service import TABLES, record


@permission_required(PORTAL_AUDIT_LOG)
@require_GET
def index(request):
    form = AuditFiltersForm(request.GET)
    context = {"form": form}
    if not form.is_valid():
        return render(request, "auditlog/index.html", context, status=400)
    # Audit events have subsecond timestamps; include events from this current second.
    # Mining retains its original whole-second relative query bounds.
    query = form.to_query(now=timezone.now(), whole_seconds=False)
    events = AuditEvent.objects.all()
    if query.start is not None:
        events = events.filter(created_at__gte=query.start, created_at__lt=query.end)
    for field, column in (
        ("actor", "actor_discord_id"),
        ("event_type", "event_type"),
        ("result", "result"),
    ):
        if form.cleaned_data[field]:
            events = events.filter(**{column: form.cleaned_data[field]})
    # Only summary fields are fetched for this page, not request/metadata payloads.
    events = events.only(
        "id",
        "created_at",
        "actor_discord_id",
        "actor_display_name",
        "actor_username",
        "event_type",
        "result",
    )
    paginator = Paginator(events, int(form.cleaned_data["page_size"]))
    page = paginator.get_page(request.GET.get("page", "1")[:8])
    params = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in form.cleaned_data.items()
        if value not in (None, "")
    }
    context.update(
        page=page,
        page_numbers=paginator.get_elided_page_range(page.number, on_each_side=2),
        pagination_query=urlencode(params),
        pagination_ellipsis=paginator.ELLIPSIS,
    )
    return render(request, "auditlog/index.html", context)


def event_details(event):
    def pretty(value):
        return json.dumps(value, indent=2, ensure_ascii=False)

    return [
        ("Event", event.get_event_type_display()),
        ("Event type", event.event_type),
        ("Actor", event.actor_name),
        ("Discord ID", event.actor_discord_id or "Unknown"),
        ("Username", event.actor_username),
        ("Timestamp", event.created_at.isoformat()),
        ("Result", event.get_result_display()),
        ("IP", event.ip_address or "Unknown"),
        ("Method", event.request_method),
        ("Path", event.request_path),
        ("Sanitized query", pretty(event.request_query)),
        ("User-Agent", event.user_agent),
        ("Referer", event.referer),
        ("Host", event.host),
        ("Accept-Language", event.accept_language),
        ("Event metadata", pretty(event.metadata_json)),
    ]


@permission_required(PORTAL_AUDIT_LOG)
@require_GET
def detail(request, pk):
    event = get_object_or_404(AuditEvent, pk=pk)
    details = event_details(event)
    if request.GET.get("format") == "json":
        return JsonResponse({"details": details})
    return render(request, "auditlog/detail.html", {"details": details})


@permission_required("minecraft.analytics")
@require_POST
def client_event(request):
    # This write-only endpoint records the caller's own event; it exposes no audit history.
    if request.content_type != "application/json" or len(request.body) > 2048:
        return HttpResponse(status=400)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(payload, dict) or set(payload) != {
        "event_type",
        "table",
        "old_threshold",
        "new_threshold",
    }:
        return HttpResponse(status=400)
    if (
        payload["event_type"] != EventType.THRESHOLD_CHANGED
        or not isinstance(payload["table"], str)
        or payload["table"] not in TABLES
    ):
        return HttpResponse(status=400)
    if (
        any(
            type(payload[key]) is not int or payload[key] not in SAMPLE_OPTIONS
            for key in ("old_threshold", "new_threshold")
        )
        or payload["old_threshold"] == payload["new_threshold"]
    ):
        return HttpResponse(status=400)
    page = TABLES[payload["table"]]
    ok = record(
        request, EventType.THRESHOLD_CHANGED, metadata={**payload, "material_group": page.slug}
    )
    return HttpResponse(status=204 if ok else 503)
