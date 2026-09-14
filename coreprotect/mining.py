"""Semantic diamond analytics types and the shared CoreProtect player-record rule."""

from dataclasses import dataclass
from datetime import UTC, datetime

DIAMOND_MATERIALS = ("minecraft:diamond_ore", "minecraft:deepslate_diamond_ore")
PLAYER_UUID_PATTERN = (
    "^([0-9a-fA-F]{32}|"
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
NIL_UUID = "0" * 32


@dataclass(frozen=True)
class DiamondQuery:
    """UTC, inclusive start / exclusive end; bounds apply only to candidate breaks."""

    start: datetime | None = None
    end: datetime | None = None
    world_id: int | None = None

    def __post_init__(self):
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("Mining query timestamps must be timezone-aware.")
                object.__setattr__(self, name, value.astimezone(UTC))
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("Start must precede end.")
        if self.world_id is not None and (type(self.world_id) is not int or self.world_id < 0):
            raise ValueError("World must be a resolved non-negative integer ID.")


@dataclass(frozen=True)
class DiamondStatsRow:
    player_uuid: str
    player_name: str
    diamond_ore: int
    deepslate_diamond_ore: int

    @property
    def total(self):
        return self.diamond_ore + self.deepslate_diamond_ore


def player_record_predicate(alias):
    """Internal SQL fragment: the alias is fixed by repository code, never user input.

    Both breakers and placers must have a named, non-# record with a valid non-nil UUID.
    Accept hyphenated and compact UUIDs, including offline/Bedrock identities. This is
    record classification, not an external Minecraft account-verification service.
    """
    if alias not in {"u", "placer"}:
        raise ValueError("Unknown player query alias.")
    return (
        f"{alias}.user <> '' AND {alias}.user NOT LIKE %s "
        f"AND {alias}.uuid REGEXP %s "
        f"AND LOWER(REPLACE({alias}.uuid, '-', '')) <> %s",
        ("#%", PLAYER_UUID_PATTERN, NIL_UUID),
    )
