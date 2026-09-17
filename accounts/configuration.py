import re

from django.core.exceptions import ImproperlyConfigured


def parse_access_override_ids(raw):
    """Positive, canonical ASCII uint64 snowflakes; reject bad owner configuration."""
    identifiers = set()
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > 2**64 - 1:
            raise ImproperlyConfigured(
                "DISCORD_ACCESS_OVERRIDE_USER_IDS must contain comma-separated numeric Discord IDs."
            )
        identifiers.add(value)
    return frozenset(identifiers)
