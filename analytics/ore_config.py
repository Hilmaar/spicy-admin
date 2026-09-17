"""Small, code-defined catalog shared by navigation, reports, and table rendering."""

from dataclasses import dataclass

from django.urls import reverse

from coreprotect.mining import ANCIENT_DEBRIS, DIAMONDS, EMERALD, OreGroup

SAMPLE_OPTIONS = (250, 500, 1000, 2500, 5000, 10000)


@dataclass(frozen=True)
class TableConfig:
    key: str
    title: str
    target_index: int
    base_index: int
    target_label: str
    base_label: str
    rate_label: str
    inverse_label: str
    default_threshold: int = 1000

    def __post_init__(self):
        if self.default_threshold not in SAMPLE_OPTIONS:
            raise ValueError("Table default must be an allowed sample threshold.")


@dataclass(frozen=True)
class OrePage:
    group: OreGroup
    label: str
    title: str
    singular: str
    tables: tuple[TableConfig, ...]
    # Optional local static path, configured only after the asset exists.
    image: str = ""
    logical_world: str = "world"

    @property
    def slug(self):
        return self.group.slug

    @property
    def url(self):
        return reverse(f"analytics:{self.slug}")


PAGES = (
    OrePage(
        DIAMONDS,
        "Diamonds",
        "Diamond Mining Statistics",
        "diamond",
        (
            TableConfig(
                "deepslate-diamonds",
                "Deepslate Diamond Mining",
                1,
                1,
                "Deepslate Diamond Ore",
                "Deepslate",
                "Diamonds per 1,000 Deepslate",
                "Deepslate per Diamond",
            ),
            TableConfig(
                "normal-diamonds",
                "Normal Diamond Mining",
                0,
                0,
                "Diamond Ore",
                "Stone",
                "Diamonds per 1,000 Stone",
                "Stone per Diamond",
            ),
        ),
    ),
    OrePage(
        ANCIENT_DEBRIS,
        "Ancient Debris",
        "Ancient Debris Mining Statistics",
        "ancient debris",
        (
            TableConfig(
                "ancient-debris",
                "Ancient Debris Mining",
                0,
                0,
                "Ancient Debris",
                "Netherrack",
                "Ancient Debris per 1,000 Netherrack",
                "Netherrack per Ancient Debris",
            ),
        ),
        logical_world="world_nether",
    ),
    OrePage(
        EMERALD,
        "Emerald",
        "Emerald Mining Statistics",
        "emerald",
        (
            TableConfig(
                "deepslate-emerald",
                "Deepslate Emerald Mining",
                1,
                1,
                "Deepslate Emerald Ore",
                "Deepslate",
                "Emeralds per 1,000 Deepslate",
                "Deepslate per Emerald",
            ),
            TableConfig(
                "normal-emerald",
                "Normal Emerald Mining",
                0,
                0,
                "Emerald Ore",
                "Stone",
                "Emeralds per 1,000 Stone",
                "Stone per Emerald",
            ),
        ),
    ),
)
PAGE_BY_SLUG = {page.slug: page for page in PAGES}
