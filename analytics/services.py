import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from coreprotect.mining import DIAMONDS, DiamondQuery, DiamondStatsRow
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
    key = f"diamonds:v2:report:{digest}"
    report = _get_cached(key)
    if report is None:
        repository = get_repository()
        targets = repository.get_diamond_stats(query)
        denominators = repository.get_denominator_stats(query, DIAMONDS)
        rows = merge_diamond_rows(targets, denominators)
        report = DiamondReport(query, rows, now)
        _set_cached(key, report)
    return report


def merge_diamond_rows(targets, denominators):
    """Full union by normalized UUID; missing sides are zero, never missing players."""
    players = {}
    for rows, offset in ((targets, 0), (denominators, 2)):
        for row in rows:
            uuid = row.player_uuid.replace("-", "").lower()
            entry = players.setdefault(uuid, [row.player_name, 0, 0, 0, 0])
            entry[0] = min(entry[0], row.player_name)
            counts = (row.diamond_ore, row.deepslate_diamond_ore) if offset == 0 else row.counts
            for i, count in enumerate(counts):
                entry[1 + offset + i] += count
    result = [DiamondStatsRow(uuid, *values) for uuid, values in players.items()]
    return tuple(sorted(result, key=lambda row: (-row.total, row.player_name, row.player_uuid)))
