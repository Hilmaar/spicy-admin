from django.db import DatabaseError
from django.shortcuts import render

from accounts.permissions import permission_required
from coreprotect.repository import CoreProtectUnavailable

from . import services
from .forms import RANGES, DiamondFiltersForm
from .ore_config import PAGE_BY_SLUG, PAGES, SAMPLE_OPTIONS
from .rollups import RollupUnavailable


@permission_required("minecraft.analytics")
def detail(request, slug="diamonds"):
    page = PAGE_BY_SLUG[slug]
    context = {
        "unavailable": False,
        "ore_page": page,
        "ore_pages": PAGES,
        "sample_options": SAMPLE_OPTIONS,
    }
    try:
        worlds = services.list_worlds()
        form = DiamondFiltersForm(request.GET, worlds=worlds)
        context["form"] = form
        if not form.is_valid():
            return render(request, "analytics/detail.html", context, status=400)
        context["range_label"] = dict(RANGES)[form.cleaned_data["range"]]
        context["world_label"] = dict(form.fields["world"].choices)[form.cleaned_data["world"]]
        context["report"] = services.get_report(form, page.group)
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
    return render(request, "analytics/overview.html", {"ore_pages": PAGES, "cards": cards})
