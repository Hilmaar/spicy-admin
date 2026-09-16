import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from coreprotect.mining import SMALL_SAMPLE_BASE_BLOCKS, DiamondQuery, DiamondStatsRow, ratio
from coreprotect.repository import get_repository

from . import rollups

CACHE_SECONDS = 45


@dataclass(frozen=True)
class DiamondReport:
    query: DiamondQuery
    rows: tuple[DiamondStatsRow, ...]
    checked_at: datetime
    base_updated_at: datetime
    base_reconciled_at: datetime | None
    base_warning: bool

    @property
    def normal_rows(self):
        return layer_rows(self.rows, "diamond_ore", "stone")

    @property
    def deepslate_rows(self):
        return layer_rows(self.rows, "deepslate_diamond_ore", "deepslate")


@dataclass(frozen=True)
class MiningLayerRow:
    player_uuid: str
    player_name: str
    target_count: int
    base_count: int

    @property
    def per_1000(self):
        return ratio(self.target_count * 1000, self.base_count)

    @property
    def per_target(self):
        return ratio(self.base_count, self.target_count)

    @property
    def small_sample(self):
        return self.base_count < SMALL_SAMPLE_BASE_BLOCKS


def layer_rows(rows, target, base):
    selected = [
        MiningLayerRow(r.player_uuid, r.player_name, getattr(r, target), getattr(r, base))
        for r in rows
        if getattr(r, target) > 0
    ]
    return tuple(sorted(selected, key=lambda r: (-r.target_count, r.player_name, r.player_uuid)))


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
    snapshot = rollups.read_snapshot(query, now)
    range_name = form.cleaned_data["range"]
    # Relative ranges use their selection, not a constantly changing `now`, as the key.
    # The cached report retains the exact bounds used, so the UI never labels old data
    # with newly calculated bounds. Custom bounds are canonical UTC ISO timestamps.
    identity = {
        "range": range_name,
        "start": query.start.isoformat() if range_name == "custom" else None,
        "end": query.end.isoformat() if range_name == "custom" else None,
        "world": query.world_id,
        "sync_generation": snapshot.generation,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    key = f"diamonds:v4:report:{digest}"
    report = _get_cached(key)
    if report is None:
        repository = get_repository()
        targets = repository.get_diamond_stats(query)
        denominators = rollups.denominators(snapshot, repository)
        rows = merge_diamond_rows(targets, denominators)
        report = DiamondReport(
            query, rows, now, snapshot.updated_at, snapshot.reconciled_at, snapshot.warning
        )
        _set_cached(key, report)
    return report


def merge_diamond_rows(targets, denominators):
    """Attach base counts to natural-diamond miners by normalized UUID."""
    players = {}
    for rows, offset in ((targets, 0), (denominators, 2)):
        for row in rows:
            uuid = row.player_uuid.replace("-", "").lower()
            if offset == 2 and uuid not in players:
                continue
            entry = players.setdefault(uuid, [row.player_name, 0, 0, 0, 0])
            if row.player_name:
                entry[0] = min(entry[0], row.player_name)
            counts = (row.diamond_ore, row.deepslate_diamond_ore) if offset == 0 else row.counts
            for i, count in enumerate(counts):
                entry[1 + offset + i] += count
    result = [
        DiamondStatsRow(uuid, *values)
        for uuid, values in players.items()
        if values[1] + values[2] > 0
    ]
    return tuple(sorted(result, key=lambda row: (-row.total, row.player_name, row.player_uuid)))
