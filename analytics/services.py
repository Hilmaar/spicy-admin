from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction

from django.core.cache import cache
from django.utils import timezone

from coreprotect.mining import (
    DIAMONDS,
    SMALL_SAMPLE_BASE_BLOCKS,
    DiamondQuery,
    DiamondStatsRow,
    MaterialBreakRow,
    ratio,
)
from coreprotect.repository import CoreProtectUnavailable, get_repository

from . import rollups

CACHE_SECONDS = 45


@dataclass(frozen=True)
class DiamondReport:
    query: DiamondQuery
    rows: tuple[DiamondStatsRow | OrePlayerRow, ...]
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
    threshold: int = SMALL_SAMPLE_BASE_BLOCKS

    @property
    def per_1000(self):
        return ratio(self.target_count * 1000, self.base_count)

    @property
    def per_target(self):
        return ratio(self.base_count, self.target_count)

    @property
    def small_sample(self):
        return self.base_count < self.threshold


def layer_rows(rows, target, base):
    selected = [
        MiningLayerRow(r.player_uuid, r.player_name, getattr(r, target), getattr(r, base))
        for r in rows
        if getattr(r, target) > 0
    ]
    return sort_layer(selected)


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


def get_report(form, group=DIAMONDS, *, world_id=None):
    now = timezone.now()
    query = form.to_query(now=now)
    if world_id is not None:
        query = replace(query, world_id=world_id)
    snapshot = rollups.read_snapshot(query, now, group)
    range_name = form.cleaned_data["range"]
    # Relative ranges use their selection, not a constantly changing `now`, as the key.
    # The cached report retains the exact bounds used, so the UI never labels old data
    # with newly calculated bounds. Custom bounds are canonical UTC ISO timestamps.
    identity = {
        "group": group.slug,
        "range": range_name,
        "start": query.start.isoformat() if range_name == "custom" else None,
        "end": query.end.isoformat() if range_name == "custom" else None,
        "world": query.world_id,
        "sync_generation": snapshot.generation,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    key = f"mining:v6:report:{digest}"
    report = _get_cached(key)
    if report is None:
        repository = get_repository()
        targets = read_targets(repository, query, group)
        denominators = rollups.denominators(snapshot, repository, group)
        merged = merge_ore_rows(targets, denominators, len(group.denominator_materials))
        # Preserve the established diamond service result for internal callers.
        rows = (
            tuple(
                DiamondStatsRow(r.player_uuid, r.player_name, *r.targets, *r.bases) for r in merged
            )
            if group == DIAMONDS
            else merged
        )
        report = DiamondReport(
            query, rows, now, snapshot.updated_at, snapshot.reconciled_at, snapshot.warning
        )
        _set_cached(key, report)
    return report


def merge_diamond_rows(targets, denominators):
    """Attach base counts to natural-diamond miners by normalized UUID."""
    converted = tuple(
        MaterialBreakRow(r.player_uuid, r.player_name, (r.diamond_ore, r.deepslate_diamond_ore))
        for r in targets
    )
    merged = merge_ore_rows(converted, denominators, 2)
    result = tuple(
        DiamondStatsRow(r.player_uuid, r.player_name, *r.targets, *r.bases) for r in merged
    )
    return tuple(sorted(result, key=lambda row: (-row.total, row.player_name, row.player_uuid)))


@dataclass(frozen=True)
class OrePlayerRow:
    player_uuid: str
    player_name: str
    targets: tuple[int, ...]
    bases: tuple[int, ...]


def read_targets(repository, query, group):
    if group == DIAMONDS:
        return tuple(
            MaterialBreakRow(r.player_uuid, r.player_name, (r.diamond_ore, r.deepslate_diamond_ore))
            for r in repository.get_diamond_stats(query)
        )
    return repository.get_material_stats(query, group.target_materials, natural_only=True)


def merge_ore_rows(targets, bases, base_count):
    players = {}
    for row in targets:
        uuid = row.player_uuid.replace("-", "").lower()
        entry = players.setdefault(uuid, [row.player_name, [0] * len(row.counts), [0] * base_count])
        entry[0] = min(entry[0], row.player_name)
        for i, count in enumerate(row.counts):
            entry[1][i] += count
    for row in bases:
        uuid = row.player_uuid.replace("-", "").lower()
        if uuid not in players:
            continue
        entry = players[uuid]
        if row.player_name:
            entry[0] = min(entry[0], row.player_name)
        for i, count in enumerate(row.counts):
            entry[2][i] += count
    return tuple(
        OrePlayerRow(uuid, name, tuple(targets), tuple(bases))
        for uuid, (name, targets, bases) in sorted(players.items())
        if sum(targets) > 0
    )


def sort_layer(rows):
    # Missing ratios are last within either sample class. Ties never depend on DB order.
    return tuple(
        sorted(
            rows,
            key=lambda r: (
                r.small_sample,
                r.base_count == 0,
                -Fraction(r.target_count, r.base_count) if r.base_count else 0,
                r.player_name.lower(),
                r.player_name,
                r.player_uuid,
            ),
        )
    )


def report_tables(report, page):
    tables = []
    for config in page.tables:
        rows = []
        for player in report.rows:
            if isinstance(player, DiamondStatsRow):
                targets = (player.diamond_ore, player.deepslate_diamond_ore)
                bases = (player.stone, player.deepslate)
            else:
                targets, bases = player.targets, player.bases
            if targets[config.target_index] > 0:
                rows.append(
                    MiningLayerRow(
                        player.player_uuid,
                        player.player_name,
                        targets[config.target_index],
                        bases[config.base_index],
                        config.default_threshold,
                    )
                )
        tables.append({"config": config, "rows": sort_layer(rows)})
    return tables


@dataclass(frozen=True)
class OverviewMetric:
    total: int
    players: int
    checked_at: datetime


def configured_world(page):
    matches = [world for world in list_worlds() if world.name == page.logical_world]
    if len(matches) != 1:
        raise CoreProtectUnavailable("Configured ore world is unavailable.")
    return matches[0]


def overview_metric(group):
    from .ore_config import PAGE_BY_SLUG

    page = PAGE_BY_SLUG[group.slug]
    world = configured_world(page)
    key = f"mining:v2:overview:{group.slug}:{world.id}:all"
    metric = _get_cached(key)
    if metric is None:
        targets = read_targets(get_repository(), DiamondQuery(world_id=world.id), group)
        merged = merge_ore_rows(targets, (), 0)
        metric = OverviewMetric(sum(sum(r.targets) for r in merged), len(merged), timezone.now())
        _set_cached(key, metric)
    return metric
