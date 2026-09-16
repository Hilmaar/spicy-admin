# Phase 2B.1 mining rollups

All Time is the default and primary view. Production stone/deepslate scans exceeded the
three-second limit despite the existing `type` index hint and aggregation before joining
players. Reports now use compact portal PostgreSQL aggregates. **All Time must never fall
back to a live full-history denominator scan, including before initialization.** Natural
diamond queries remain direct, strict, and authoritative against CoreProtect.

## Storage and source semantics

`analytics/migrations/0001_initial.py` creates only portal PostgreSQL tables:

| Model | Stored values |
| --- | --- |
| `MiningMaterialDaily` | UTC `date`, normalized `player_uuid`, logical `world_id`, stable `material_key`, `break_count` |
| `MiningAnalyticsSyncState` | Source name, committed rowid watermark, captured backfill target, initialization flag, material configuration signature, generation, success/reconciliation timestamps, safe error text |

Daily identity is unique across `(date, player_uuid, world_id, material_key)`. Additional
indexes support material/date and world/material/date filtering. Counts are big integers.
No raw events, blobs, CoreProtect numeric material identities, or player names are copied.
`analytics/rollup_config.py` centrally maps `stone` and `deepslate` to material names and
defines batch, reconciliation, freshness, and lock constants. Adding materials requires a
full rebuild; a configuration signature blocks use of an incompatible rollup.

The repository dynamically resolves names through `co_material_map`. Each count requires
`action=0`, `rolled_back=0`, and the existing real-player name/non-nil UUID predicate.
World IDs come from source events and dynamic world mappings. UUIDs are lowercase without
hyphens; historical user IDs sharing a UUID combine. Previously placed stone/deepslate
remain included. Diamond placement exclusion, including earlier same-second rowids and
placements before the report window, is unchanged.

## Sync and recovery

```bash
python manage.py sync_mining_analytics
python manage.py sync_mining_analytics --batch-size 5000
python manage.py sync_mining_analytics --reconcile-only
python manage.py sync_mining_analytics --reconcile-hours 72
python manage.py sync_mining_analytics --full-rebuild
```

Default batch size is 10,000 source rows; allowed sizes are 1–50,000. A source PRIMARY-key
reader finds a bounded batch end, including irrelevant rowids/gaps so progress never gets
stuck. Only configured material counts are aggregated within that interval. The inner
aggregate groups UTC day/user/world/material before joining and classifying player records.
The source remains SELECT-only under existing read-only transactions and statement/socket
timeouts. No source index is created or altered.

Initial backfill captures a high-water rowid and persists it. Each batch atomically adds
counts and advances the watermark in PostgreSQL. A crash before commit leaves both
unchanged; a crash afterward resumes above the committed rowid. Incomplete initial or full
backfills never expose ratios. Run the ordinary command again to resume an interrupted
backfill. Repeating `--full-rebuild` deliberately restarts it instead.

Subsequent runs capture a new high-water mark and read only rowids above the committed
watermark through that target. Rows arriving during the run are handled next time. Run
another ordinary sync after a long initial backfill to catch up. `last_success_at` is the
completion time, not proof that writes arriving after the captured target were ingested.
Source rowids must be monotonic and committed in recording order. A decreasing high-water
mark is rejected. An undetectable source replacement, purge, or reset with reused IDs needs
operator review and a full rebuild; never reuse another map's rollup without rebuilding.

A PostgreSQL session advisory lock spans all batch commits and reconciliation, so a second
run exits clearly without changing counts. Process/connection exit releases the lock.
SQLite locking exists only for local tests. The production command requires the existing
direct PostgreSQL connection; do not place a transaction-pooling proxy in front of this
session lock. Report reads briefly lock the sync-state row while reading local SUMs to
pair counts with the correct generation; they never hold that lock during CoreProtect calls.

## Rollback reconciliation

After forward ingestion, rebuild the configured recent window (default 48 hours), expanded
to all intersecting UTC date buckets, usually three dates. Each day's source query uses
the existing `type` index and `rowid <= committed watermark`, preventing reconciliation
from ingesting rows that a later forward batch would count again. Read replacement
aggregates first, then delete/replace only those dates/materials in one atomic PostgreSQL
transaction. A failed read or replacement preserves the previous buckets.

Changes outside these recent dates are **not** automatically reconciled. Use a reviewed
`--full-rebuild` after older rollbacks/restores, history purges, or source/material changes.
Full rebuild clears only these application rollups, resets the watermark, and temporarily
makes ratios unavailable. It never modifies CoreProtect. `--reconcile-only` requires a
completed backfill, does not advance rowids, and does not refresh forward-sync freshness.

The source reads are separate snapshots. Concurrent gameplay and rollback changes may be
observed between reads; later reconciliation repairs recent differences. This is eventual
consistency, not a transaction spanning MariaDB and PostgreSQL.

## Report ranges, cache, and freshness

Whole UTC days use PostgreSQL SUMs, with optional logical world filtering. Exact partial
ranges use complete interior days plus at most two disjoint live boundary queries, each
strictly shorter than 24 hours. For September 1 14:30 through September 10 18:15:

| Portion | Source |
| --- | --- |
| September 1 14:30 to September 2 00:00 | CoreProtect boundary |
| September 2 00:00 to September 10 00:00 | PostgreSQL daily buckets |
| September 10 00:00 to September 10 18:15 | CoreProtect boundary |

Same-day ranges use one boundary. Midnight-aligned ranges use no live denominator queries.
All Time sums every stored bucket, including the current day's ingested portion, with no
live denominator boundary. Start remains inclusive and end exclusive; UTC offsets and
subsecond bounds retain the existing server validation and integer-event comparison rules.
No partial result is returned if a required source fails.

The page displays last successful sync and reconciliation times. No initialized sync or
incompatible configuration yields an explicit 503 initialization state without ratios.
After 15 minutes, or a failed latest sync, a visible warning accompanies previously
complete data. After 24 hours without successful forward sync, ratios are unavailable.
These constants are centralized. Never claim a stale denominator is synchronized with
the live natural count or boundary reads.

The existing 45-second LocMem report cache includes range, exact custom bounds, world, and
sync generation. Every committed batch/reconciliation and recorded failure advances the
generation. Readiness and hard expiry are checked before cache access. Authorization and
Discord role revalidation remain ahead of analytics. No Redis or external cache is added.

## Separate tables and preserved controls

| Table | Columns and formulas |
| --- | --- |
| Normal Diamond Mining | Player; Diamond Ore; Stone; `diamond_ore / stone * 1000`; `stone / diamond_ore` |
| Deepslate Diamond Mining | Player; Deepslate Diamond Ore; Deepslate; `deepslate_diamond_ore / deepslate * 1000`; `deepslate / deepslate_diamond_ore` |

Each table includes only players with positive natural targets in that layer and sorts
target descending, name ascending, UUID ascending. Denominator-only miners never appear.
Both use two-decimal ratios, a dash for zero divisors, and a layer-specific Small sample
label below `SMALL_SAMPLE_BASE_BLOCKS` (1,000). Each table scrolls independently with sticky
headers. Dark/light themes, responsive navigation, calendar hover/keyboard behavior,
radial clock, UTC whole-date defaults, Cancel, and plain-input fallback are preserved.

## Production sequence and validation still required

These are instructions for a later authorized release, not actions performed by this change.

1. Review and back up the existing portal PostgreSQL database. Stage the reviewed code/image
   through the existing release workflow. Preserve legacy Compose 1.25 / version 3.7.
2. Apply portal migrations with the new image before serving its analytics code:
   `docker-compose run --rm web python manage.py migrate`.
   Existing startup also runs migrations, but explicitly verify the new migration is applied.
3. Initialize with `docker-compose run --rm web python manage.py sync_mining_analytics`.
   The portal shows initialization until completion; it must not run the old live fallback.
   Run it again to catch up. If interrupted, resume using the same command. Smaller
   `--batch-size` can reduce forward query cost without increasing timeouts.
4. With the SELECT-only source account, validate dynamic materials/worlds, UUID normalization,
   known player/placed/rolled-back events, batch boundaries/gaps, and daily UTC totals.
   Compare a small known sample to direct bounded queries. Validate MariaDB EXPLAIN/timing
   for PRIMARY batches, `type` reconciliation and partial boundaries under existing limits.
   A timeout fails safely; resolve the query plan in a separately reviewed change if needed.
5. On an isolated PostgreSQL/MariaDB validation setup, interrupt and resume a sync, run
   overlapping commands, confirm no duplicate totals, and test recent rollback replacement
   versus older history requiring rebuild. Verify the actual PostgreSQL advisory lock and
   conflict-upsert behavior; local SQLite fixtures do not prove production concurrency.
6. Check All Time, 24h/7d/30d, precise/midnight custom ranges, world selection, both tables,
   freshness/initialization, permission denial/revocation, and existing OAuth/diagnostics.
   Confirm All Time makes zero live denominator requests.
7. Later, configure a separately approved cron/systemd invocation every five minutes using
   the existing Compose command and project directory. No host scheduler is installed here.
   Until scheduled, run manually; without successful refresh the 15-minute/24-hour states
   apply. Monitor command exit status and timestamps without logging secrets.

No worker framework, additional ore pages, raw-event copy, scores, alerts, live feed,
player pages, punishments, Discord bot, or Pterodactyl integration is included. No push,
merge, deploy, infrastructure change, CoreProtect migration/index change, or timeout
increase is part of this phase.
