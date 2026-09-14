import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from coreprotect.mining import DiamondQuery, DiamondStatsRow
from coreprotect.repository import get_repository

CACHE_SECONDS = 45


@dataclass(frozen=True)
class DiamondReport:
    query: DiamondQuery
    rows: tuple[DiamondStatsRow, ...]
    checked_at: datetime


def _get_cached(key):
    try:
        return cache.get(key)
    except Exception:
        # Best-effort result caching must never invent results or bypass authorization.
        return None


def _set_cached(key, value):
    try:
        cache.set(key, value, timeout=CACHE_SECONDS)
    except Exception:
        pass


def list_worlds():
    key = "diamonds:v1:worlds"
    worlds = _get_cached(key)
    if worlds is None:
        worlds = tuple(get_repository().list_worlds())
        _set_cached(key, worlds)
    return worlds


def get_report(form):
    now = timezone.now()
    query = form.to_query(now=now)
    range_name = form.cleaned_data["range"]
    # Relative ranges use their selection, not a constantly changing `now`, as the key.
    # The cached report retains the exact bounds used, so the UI never labels old data
    # with newly calculated bounds. Custom bounds are canonical UTC ISO timestamps.
    identity = {
        "range": range_name,
        "start": query.start.isoformat() if range_name == "custom" else None,
        "end": query.end.isoformat() if range_name == "custom" else None,
        "world": query.world_id,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    key = f"diamonds:v1:report:{digest}"
    report = _get_cached(key)
    if report is None:
        rows = get_repository().get_diamond_stats(query)
        report = DiamondReport(query, rows, now)
        _set_cached(key, report)
    return report
