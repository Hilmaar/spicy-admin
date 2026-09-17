from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts.permissions import permission_required
from auditlog.events import ORE_EVENTS, EventType, Result
from auditlog.service import record, thresholds
from coreprotect.repository import CoreProtectUnavailable

from . import services
from .forms import TimeRangeForm
from .ore_config import PAGE_BY_SLUG, PAGES, SAMPLE_OPTIONS
from .rollups import RollupUnavailable


@permission_required("minecraft.analytics")
@ensure_csrf_cookie
def detail(request, slug="diamonds"):
    page = PAGE_BY_SLUG[slug]
    context = {
        "unavailable": False,
        "ore_page": page,
        "ore_pages": PAGES,
        "sample_options": SAMPLE_OPTIONS,
    }
    try:
        form = TimeRangeForm(request.GET)
        context["form"] = form
        if not form.is_valid():
            return render(request, "analytics/detail.html", context, status=400)
        world = services.configured_world(page)
        context["report"] = services.get_report(form, page.group, world_id=world.id)
        context["tables"] = services.report_tables(context["report"], page)
    except RollupUnavailable as error:
        context["unavailable"] = True
        context["rollup_message"] = str(error)
    except DatabaseError:
        context["unavailable"] = True
        context["rollup_message"] = "Base-block analytics are unavailable. Contact a portal owner."
    except CoreProtectUnavailable:
        # No SQL, hostnames, exception details, or credentials in the public state.
        context["unavailable"] = True
    if request.method == "GET":
        result = Result.ERROR if context["unavailable"] else Result.SUCCESS
        metadata = {"material_group": page.slug}
        if "report" in context:
            query = context["report"].query
            metadata.update(
                range=form.cleaned_data["range"],
                start=query.start.isoformat() if query.start else None,
                end=query.end.isoformat() if query.end else None,
                thresholds=thresholds(request.GET.get("thresholds"), page.slug),
            )
        record(request, ORE_EVENTS[page.slug], result=result, metadata=metadata)
        if "report" in context and any(key in request.GET for key in ("range", "start", "end")):
            record(request, EventType.FILTERED, metadata=metadata)
    return render(
        request, "analytics/detail.html", context, status=503 if context["unavailable"] else 200
    )


@permission_required("minecraft.analytics")
def overview(request):
    cards = []
    for page in PAGES:
        try:
            metric = services.overview_metric(page.group)
        except CoreProtectUnavailable:
            metric = None
        cards.append({"page": page, "metric": metric})
    if request.method == "GET":
        record(request, EventType.ORE_OVERVIEW)
    return render(request, "analytics/overview.html", {"ore_pages": PAGES, "cards": cards})
