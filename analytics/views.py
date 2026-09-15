from django.shortcuts import render

from accounts.permissions import permission_required
from coreprotect.mining import SMALL_SAMPLE_BASE_BLOCKS
from coreprotect.repository import CoreProtectUnavailable

from . import services
from .forms import RANGES, DiamondFiltersForm


@permission_required("minecraft.analytics")
def diamonds(request):
    context = {"unavailable": False, "small_sample_threshold": SMALL_SAMPLE_BASE_BLOCKS}
    try:
        worlds = services.list_worlds()
        form = DiamondFiltersForm(request.GET, worlds=worlds)
        context["form"] = form
        if not form.is_valid():
            return render(request, "analytics/diamonds.html", context, status=400)
        context["range_label"] = dict(RANGES)[form.cleaned_data["range"]]
        context["world_label"] = dict(form.fields["world"].choices)[form.cleaned_data["world"]]
        context["report"] = services.get_report(form)
    except CoreProtectUnavailable:
        # No SQL, hostnames, exception details, or credentials in the public state.
        context["unavailable"] = True
    return render(
        request, "analytics/diamonds.html", context, status=503 if context["unavailable"] else 200
    )
