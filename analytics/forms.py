from datetime import UTC, timedelta

from django import forms
from django.utils import timezone

from coreprotect.mining import DiamondQuery

RANGES = (
    ("all", "All time"),
    ("24h", "Last 24 hours"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("custom", "Custom range"),
)
RANGE_DURATIONS = {"24h": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}


class UTCDateTimeField(forms.DateTimeField):
    def to_python(self, value):
        if isinstance(value, str) and len(value) > 64:
            raise forms.ValidationError("Enter a valid date and time.")
        # The visible controls explicitly say UTC, regardless of any active user timezone.
        try:
            with timezone.override(UTC):
                value = super().to_python(value)
            return value.astimezone(UTC) if value is not None else None
        except (ValueError, OverflowError):
            raise forms.ValidationError("Enter a valid date and time.") from None


class DiamondFiltersForm(forms.Form):
    range = forms.ChoiceField(label="Time range", choices=RANGES)
    world = forms.ChoiceField(label="World", required=False)
    start = UTCDateTimeField(
        label="Start (UTC)",
        required=False,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M:%S",
            attrs={
                "type": "text",
                "placeholder": "YYYY-MM-DDTHH:MM:SS",
                "aria-describedby": "range-help",
            },
        ),
    )
    end = UTCDateTimeField(
        label="End (UTC, exclusive)",
        required=False,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M:%S",
            attrs={
                "type": "text",
                "placeholder": "YYYY-MM-DDTHH:MM:SS",
                "aria-describedby": "range-help",
            },
        ),
    )

    def __init__(self, data, *, worlds):
        data = data.copy()
        data.setdefault("range", "all")
        data.setdefault("world", "")
        super().__init__(data)
        self.fields["world"].choices = [("", "All worlds")] + [
            (str(world.id), world.name) for world in worlds
        ]

    def clean(self):
        data = super().clean()
        if data.get("range") == "custom":
            for field in ("start", "end"):
                if not data.get(field) and field not in self.errors:
                    self.add_error(field, "Enter both bounds for a custom range.")
            if data.get("start") and data.get("end") and data["start"] >= data["end"]:
                self.add_error("end", "End must be after start.")
        elif data.get("start") or data.get("end"):
            self.add_error("range", "Choose Custom range to apply start and end timestamps.")
        return data

    def to_query(self, *, now):
        if not self.is_valid():
            raise ValueError("Cannot query with invalid filters.")
        data = self.cleaned_data
        start = end = None
        if data["range"] in RANGE_DURATIONS:
            end = now.astimezone(UTC).replace(microsecond=0)
            start = end - RANGE_DURATIONS[data["range"]]
        elif data["range"] == "custom":
            start, end = data["start"], data["end"]
        return DiamondQuery(start, end, int(data["world"]) if data["world"] else None)
