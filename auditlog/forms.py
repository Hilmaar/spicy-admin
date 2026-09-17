from django import forms
from django.db.models import Max

from analytics.forms import TimeRangeForm

from .events import EventType, Result
from .models import AuditEvent


class AuditFiltersForm(TimeRangeForm):
    actor = forms.ChoiceField(label="Actor", required=False)
    event_type = forms.ChoiceField(
        label="Event type", required=False, choices=[("", "All events"), *EventType.choices]
    )
    result = forms.ChoiceField(
        label="Result", required=False, choices=[("", "All results"), *Result.choices]
    )
    page_size = forms.ChoiceField(label="Entries per page", choices=(("50", "50"), ("100", "100")))

    def __init__(self, data):
        data = data.copy()
        data.setdefault("page_size", "100")
        super().__init__(data, default_range="7d")
        actors = (
            AuditEvent.objects.exclude(actor_discord_id=None)
            .order_by()
            .values("actor_discord_id")
            .annotate(name=Max("actor_display_name"), username=Max("actor_username"))
            .order_by("actor_discord_id")
        )
        self.fields["actor"].choices = [("", "All users")] + [
            (
                row["actor_discord_id"],
                f"{row['name'] or row['username'] or 'Unknown'} ({row['actor_discord_id']})",
            )
            for row in actors
        ]
