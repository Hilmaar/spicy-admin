"""Compact read-side objects. No external database models or event persistence."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MiningBucket:
    date: date
    player_uuid: str
    world_id: int
    material_key: str
    break_count: int


@dataclass(frozen=True)
class MiningBatch:
    through_rowid: int
    buckets: tuple[MiningBucket, ...]
