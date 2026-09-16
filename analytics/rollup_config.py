"""Application configuration, not CoreProtect numeric IDs or host scheduler settings."""

ROLLUP_MATERIALS = {
    "stone": "minecraft:stone",
    "deepslate": "minecraft:deepslate",
    "netherrack": "minecraft:netherrack",
}
SOURCE_NAME = "coreprotect"
BATCH_SIZE = 10000
MAX_BATCH_SIZE = 50000
RECONCILE_HOURS = 48
STALE_WARNING_SECONDS = 15 * 60
STALE_UNAVAILABLE_SECONDS = 24 * 60 * 60
LOCK_ID = 731042819
