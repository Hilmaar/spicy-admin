from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Sum

from coreprotect.mining import DIAMONDS, DiamondQuery, MaterialBreakRow

from . import rollup_config as config
from .models import MiningAnalyticsSyncState, MiningMaterialDaily
from .sync import material_signature


class RollupUnavailable(Exception):
    pass


@dataclass(frozen=True)
class DaySplit:
    start_date: date | None
    end_date: date | None
    boundaries: tuple[DiamondQuery, ...]


def split_range(query):
    """Complete UTC buckets [start_date,end_date), plus disjoint <24h boundaries."""
    if query.start is None and query.end is None:
        return DaySplit(None, None, ())
    if query.start is None or query.end is None:
        raise ValueError("A bounded report requires both timestamps.")
    start_midnight = datetime.combine(query.start.date(), time.min, UTC)
    end_midnight = datetime.combine(query.end.date(), time.min, UTC)
    full_start = (
        start_midnight if query.start == start_midnight else start_midnight + timedelta(days=1)
    )
    if full_start > end_midnight:
        return DaySplit(query.end.date(), query.end.date(), (query,))
    boundaries = []
    if query.start < full_start:
        boundaries.append(DiamondQuery(query.start, full_start, query.world_id))
    if end_midnight < query.end:
        boundaries.append(DiamondQuery(end_midnight, query.end, query.world_id))
    return DaySplit(full_start.date(), end_midnight.date(), tuple(boundaries))


@dataclass(frozen=True)
class RollupSnapshot:
    generation: int
    updated_at: datetime
    reconciled_at: datetime | None
    warning: bool
    counts: tuple[MaterialBreakRow, ...]
    boundaries: tuple[DiamondQuery, ...]


def read_snapshot(query, now):
    parts = split_range(query)
    # Lock only while reading local metadata and SUMs, never while calling CoreProtect.
    # Sync updates the same state row atomically with every bucket commit/replacement.
    with transaction.atomic():
        state = (
            MiningAnalyticsSyncState.objects.select_for_update()
            .filter(pk=config.SOURCE_NAME)
            .first()
        )
        if (
            state is None
            or not state.initialized
            or state.last_success_at is None
            or state.material_signature != material_signature()
        ):
            raise RollupUnavailable(
                "Base-block analytics are initializing. "
                "A portal owner must complete the mining sync."
            )
        age = (now - state.last_success_at).total_seconds()
        if age > config.STALE_UNAVAILABLE_SECONDS:
            raise RollupUnavailable(
                "Base-block analytics are unavailable because the last successful sync is too old."
            )
        keys = tuple(config.ROLLUP_MATERIALS)
        # Material lookup order follows the code-defined ore group, not DB numeric IDs.
        material_keys = {name: key for key, name in config.ROLLUP_MATERIALS.items()}
        ordered = tuple(material_keys[name] for name in DIAMONDS.denominator_materials)
        rows = MiningMaterialDaily.objects.filter(material_key__in=keys)
        if parts.start_date is not None:
            rows = rows.filter(date__gte=parts.start_date, date__lt=parts.end_date)
        if query.world_id is not None:
            rows = rows.filter(world_id=query.world_id)
        counts = {}
        for row in rows.values("player_uuid", "material_key").annotate(total=Sum("break_count")):
            if row["material_key"] not in ordered:
                continue
            values = counts.setdefault(row["player_uuid"], [0] * len(ordered))
            values[ordered.index(row["material_key"])] += row["total"]
        # Names intentionally absent: display names continue to come from live targets.
        return RollupSnapshot(
            state.generation,
            state.last_success_at,
            state.last_reconciled_at,
            age > config.STALE_WARNING_SECONDS or bool(state.last_error),
            tuple(MaterialBreakRow(uuid, "", tuple(values)) for uuid, values in counts.items()),
            parts.boundaries,
        )


def denominators(snapshot, repository):
    rows = list(snapshot.counts)
    for boundary in snapshot.boundaries:
        # Never use an open-ended/full-history fallback, including before bootstrap.
        if (
            boundary.start is None
            or boundary.end is None
            or boundary.end - boundary.start >= timedelta(days=1)
        ):
            raise ValueError("Live denominator windows must be shorter than one UTC day.")
        rows.extend(repository.get_denominator_stats(boundary, DIAMONDS))
    return tuple(rows)
