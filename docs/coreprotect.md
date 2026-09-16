# CoreProtect: external, authoritative, read only

Phase 2B.2 extends this architecture to Ancient Debris/Netherrack and Emerald.
See [current groups, sorting, thresholds, and the required material-signature rebuild](ore-statistics.md).
The operational details below describe the original Phase 2B.1 foundation.

## Known production facts supplied in the specification

Production runs CoreProtect **2.24.1**, MariaDB **10.3.39**, and InnoDB. MariaDB runs
on the Docker host at TCP port 3306 and is actively written by Minecraft.
The supplied history starts around 2026-08-06; that is descriptive, not a query constant.

| Table | Approximate starting scale |
| --- | --- |
| `co_block` | 23.7 million rows; 1.8 GB data + 2.37 GB indexes, about 4.17 GB total |
| `co_container` | 7.35 million rows |
| `co_item` | 1.66 million rows |
| `co_entity` | 850,000+ rows, unusually large blobs |

Plan for hundreds of millions of events. These figures are not live portal metrics.

### Supplied `co_block` schema

| Column | Type |
| --- | --- |
| `rowid` | BIGINT AUTO_INCREMENT PRIMARY KEY |
| `time`, `user`, `wid` | INT |
| `x`, `y`, `z`, `type`, `data` | INT |
| `meta` | MEDIUMBLOB |
| `blockdata` | BLOB |
| `action`, `rolled_back` | TINYINT |

Existing indexes: primary key `(rowid)`, `(wid, x, z, time)`, `(user, time)`, and
`(type, time)`. Do not add or alter indexes automatically.

### Mappings and semantics

- `co_user`: `rowid`, `time`, `user`, `uuid`. `co_block.user` refers to its numeric
  user identifier. Pseudo-users such as `#water`, `#lava`, mobs, and environmental causes
  exist. Use UUID/user records to distinguish actual players; do not count every user as one.
- `co_world`: resolve logical `id` and `world` name. Do not confuse the mapping table's
  physical `rowid` with its logical `id`. Resource and archived worlds can be added later.
- `co_material_map`: resolve logical `id` from `material`, e.g. `minecraft:diamond_ore`.
  Material/world IDs differ between databases. No numeric IDs belong in business logic.
- `co_version`: the adapter reads `version` from the last `rowid`. This is the latest
  **recorded database version**, not a live Minecraft plugin process probe. Empty is shown
  honestly. The version and mapping column layouts are supported by the
  [upstream database definitions](https://github.com/PlayPro/CoreProtect/blob/v22.4/src/main/java/net/coreprotect/database/Database.java).
  The supplied production version/schema must still be checked through diagnostics.
- `action = 0`: removed/broken block. `action = 1`: placed block.
  Meanings of actions 2 and 3 are outside current requirements; do not guess.
- Only `rolled_back = 0` events qualify for mining analytics.

### Natural mining: Phase 2A business rule

A candidate counts only when it is a non-rolled-back break and there is **no earlier,
non-rolled-back player placement of the same material at the same world, x, y, and z**.
A placement after the break cannot retroactively invalidate that natural discovery.
Do not restrict placement lookup to the selected reporting window: a placement before
the window can still invalidate a break inside it. Event order is `(time, rowid)`:
`p.time < b.time OR (p.time = b.time AND p.rowid < b.rowid)`. This assumes CoreProtect's
rowid reflects recording order for events in the same second. Validate that assumption
against production examples; rowid does not override differing event timestamps.

Silk Touch/Fortune example: a player finds ore, mines it with Silk Touch, places it at
home, then breaks it with Fortune. The final break is not a second natural discovery.
Phase 2B deliberately does **not** apply this exclusion to stone/deepslate denominators.
Their counts may include previously player-placed blocks. Target diamonds remain strict.

## Phase 1 implementation

`coreprotect/repository.py` defines the semantic protocol and MariaDB implementation:
`check_connection()`, `get_version()`, `list_worlds()`, `resolve_world(name)`, and
`resolve_material(name)`. A future backend can implement the protocol without changing views.
Phase 2A extends this protocol with `get_diamond_stats(DiamondQuery)`; see below.

PyMySQL connects independently of Django. MariaDB 10.3 is not a Django database backend,
and migrations cannot target it through application settings. Each call opens a short-lived
connection, sets a session statement timeout, starts a READ ONLY transaction, reads, rolls
back the transaction, and closes the connection. The transaction rollback is connection
cleanup, **not a CoreProtect gameplay rollback**.

Connection, socket read/write, and MariaDB `max_statement_time` limits default to 3 seconds.
The latter also aborts timed-out statements on the server; see
[MariaDB statement timeout documentation](https://mariadb.com/docs/server/ha-and-performance/optimization-and-tuning/query-optimizations/aborting-statements).
DNS lookup and cumulative calls can add latency; the full diagnostic makes three bounded
calls. `list_worlds` caps the diagnostic display at 1,000 worlds and reports excess explicitly.
Names are parameterized. Table prefixes allow only validated alphanumeric characters and
underscores. Only fixed SELECT statements and session/transaction controls exist.

The database credential is the final enforcement boundary: a dedicated SELECT-only
MariaDB account is mandatory. Never use Minecraft's writer credentials. Do not INSERT,
UPDATE, DELETE, ALTER, CREATE, DROP, run migrations, add indexes, or perform CoreProtect
rollbacks. Only compact daily denominator aggregates are stored in portal PostgreSQL;
raw CoreProtect events are never copied. See [Phase 2B.1](mining-rollups.md).

Dashboard connectivity uses `SELECT 1`, cached for 60 seconds per worker. It does not
prove mapping-schema compatibility; Admin-only diagnostics checks that. Errors exclude
connection strings and credentials. Documentation never contacts CoreProtect. There is
no `COUNT(*)` or `co_block` scan in diagnostics.

## Manual connectivity validation

1. Have the database administrator create a SELECT-only account restricted to the appropriate
   source address/subnet. Review effective grants, including inherited privileges.
2. Set the database host, port, name, user, password, and optional table prefix in `.env`.
   On Linux use a verified Docker host bridge IP or the optional host-gateway file described
   in the README. No host IP is embedded in Python.
3. Verify the container route, existing MariaDB bind address, firewall, and account-host grants.
   MariaDB listening only on host 127.0.0.1 cannot be reached using a bridge address.
   Any required listener/firewall/grant change is a separate manual host operation; do not
   expose port 3306 publicly or change existing Docker networks to solve it.
4. Log in with the configured Admin role and visit `/diagnostics/`. Confirm the recorded
   version, worlds, and material lookup. A missing material differs from connection failure.

## Current denominator architecture and deferred work

Phase 2B.1 uses a rowid watermark and compact PostgreSQL daily aggregates for stone/deepslate.
Recent UTC days are reconciled to handle rollback changes. See [the operational guide](mining-rollups.md)
for the sync reader, bootstrap, concurrency, exact partial-day strategy, and production checks.
No other ore pages, scores, live feeds, integrations, worker frameworks, or raw event copies
are implemented. Natural diamonds retain the direct query below.

## Phase 2A: direct diamond analytics

`/ore-statistics/diamonds/` requires the existing `minecraft.analytics` permission.
It now shows separate normal/stone and deepslate/deepslate tables with layer-specific ratios.
Counts represent broken ore blocks, not item drops, fortune yields, or evidence of cheating.
Natural target results are held only in the short report cache; denominator daily totals
are persisted in portal PostgreSQL.

### Query strategy

The Phase 2A target aggregate uses two SELECTs: both material mappings and one aggregate.
All Time and whole-day reports add no live denominator SELECTs. Partial-day reports add
two SELECTs per boundary (material mapping and aggregate), for at most two boundaries.
World mappings are separately cached. Each repository call retains the existing
READ ONLY transaction, session statement limit, socket timeouts, rollback, and close.
The material lookup and aggregate use one connection/snapshot. World mappings are a
separate small query. Session control statements are in addition to those SELECTs.
No per-player requests, blobs, or `SELECT *` are used.

The aggregate begins at `co_block b` with `b.type IN (resolved diamond IDs)`, `action=0`,
`rolled_back=0`, and optional time/world bounds. The expected candidate access uses
the existing `(type,time)` index. `STRAIGHT_JOIN co_user u ON u.rowid=b.user` keeps
the rare block candidates ahead of user-record lookups. Index names are not assumed or
hardcoded. MariaDB still selects the index; check the real plan before widening use.

For each candidate, a correlated `NOT EXISTS` checks prior placements at equal wid/x/z
(the leading columns of `(wid,x,z,time)`), `p.time <= b.time`, equal y/type, `action=1`,
and `rolled_back=0`. The precise `(time,rowid)` predicate then determines whether the
placement was earlier. The placer is resolved by primary-key lookup in `co_user` using
the same real-player predicate as the breaker. There is **no lower time bound on p**.
The extra `p.time <= b.time` is redundant logically but makes the indexed upper bound explicit.

Two `SUM(CASE ...)` expressions aggregate normal and deepslate diamond counts; `COUNT(b.rowid)`
orders by total. Results group by normalized UUID and sort by total descending, player name
ascending, then UUID ascending. Sorting is over aggregated player rows, not all block events.
The web view knows no SQL or CoreProtect schema. `coreprotect/mining.py` holds semantic
types and centralized player classification; the adapter builds and executes the query.

### What qualifies as a player record

Both breakers and placers require a non-empty name not beginning with `#`, and a non-nil
UUID matching 32 hex digits or the standard 8-4-4-4-12 hyphenated representation.
Unknown user mappings, missing/malformed UUIDs, nil UUIDs, and environmental actors are
excluded. Offline and Bedrock UUIDs are accepted without imposing a UUID version.
This is a classification of available CoreProtect records, not verification against Mojang.
Validate actual UUID storage and pseudo-user conventions in production before trusting counts.

UUIDs normalize to lowercase without hyphens. Multiple `co_user` records for the same UUID
produce one row; the displayed name is `MIN(u.user)` among qualifying candidate records
under the database collation. It can be a historical name and is not claimed to be the
latest Minecraft name. Different UUIDs sharing a name remain separate players.

Both material mappings must resolve unambiguously to distinct IDs. A missing or ambiguous
mapping produces the unavailable state rather than misleading partial or zero counts.

### Time and world filters

Default: all time and all worlds, with no hardcoded history start or current-time cutoff.
Quick ranges are last 24 hours / 7 days / 30 days, measured from one UTC timestamp at query
creation, rounded down to a whole second. Start is inclusive and end is exclusive.
The current incomplete second is therefore omitted from quick ranges.
Custom ranges require both bounds and start < end. ISO dates mean midnight UTC; naive
date-times mean UTC; explicit offsets normalize to UTC. Subsecond bounds round upward
when comparing integer event seconds, preserving the inclusive/exclusive semantics.
The controls show UTC and the page labels the actual query bounds.

World choices come from the existing `list_worlds()` method. Invalid choices are rejected
before the aggregate runs. A newly added world becomes selectable after the mapping cache
expires. The existing 1,000-world safety limit is retained. Bounds filter **breaks only**.

### Best-effort cache and failures

World mappings and successful aggregate reports use the existing LocMem cache for 45 seconds.
This is per-process, not shared between Gunicorn workers. Concurrent misses may issue duplicate
queries; there is no worker, Redis dependency, or distributed cache. Keys contain the time
selection, canonical custom bounds, world ID, and sync generation, hashed to a fixed length, with no secrets.
Relative selections reuse their entry during its TTL instead of generating a new key every
second. The report retains the original bounds and query timestamp for honest UI labels.

Cache errors fall back to querying the source; DB errors propagate to a generic 503 inside
the portal shell, with no SQL/hostnames/credentials displayed. Failed queries are not cached
as empty reports. Successful empty reports show the distinct no-matching-events message.
Already-cached results can remain visible until their short TTL expires. Authorization and
Discord role revalidation happen before any analytics/cache access. Documentation never
queries analytics. Existing CoreProtect diagnostics and dashboard status retain their behavior.

### Production validation before broad use

1. Run the automated suite without production credentials. Its SQL fixture tests execute the
   actual SELECT logic on in-memory SQLite with placeholder/STRAIGHT_JOIN translation
   and removal of the MariaDB-only index hint
   and a REGEXP shim. They validate relational behavior, **not MariaDB plans or collation**.
2. With the SELECT-only account, verify both material mappings and real/pseudo-player UUID
   formats. Compare known Silk Touch/Fortune events, including same-second and old placements.
3. Use a narrow custom range and a known world first. Run a read-only `EXPLAIN` of the
   generated aggregate and inspect candidate access via `(type,time)` and placement access
   via `(wid,x,z,time)`, plus primary-key user lookups. No index changes are authorized.
   In a Django shell, resolve the two names using `repo.resolve_material`, build the SQL
   with `repo._diamond_statement(query, diamond_id, deepslate_id)`, and use `repo._cursor()`
   to execute `cursor.execute("EXPLAIN " + sql, params)`. This internal helper is for a manual
   reviewed plan check, not an additional public API. `EXPLAIN` does not execute the aggregate;
   do not substitute `ANALYZE` without understanding its actual query execution.
4. Compare factual counts against small known CoreProtect samples, then test 24h/7d/30d/all
   and world filters within the existing timeout. A large all-time query may time out; this
   must show unavailable, never silently truncated or partial results. Review the plan rather
   than automatically increasing timeouts or changing CoreProtect schema.
5. Confirm Admin/Overlord access, Patron/member denial, role revocation even with a warm
   cache, and continued documentation access during a CoreProtect outage. Do outage checks
   in an isolated validation environment, not by stopping production MariaDB.

## Phase 2B.1 denominator queries and ratios

The former full-range denominator request is superseded by
[PostgreSQL rollups and exact short boundaries](mining-rollups.md). Production All Time and
30-day scans exceeded the existing timeout even after forcing `type` and aggregating
per CoreProtect user first. This is why reports no longer execute those full-range scans.

For a live partial boundary, resolve both material names dynamically, then aggregate
`action=0`, `rolled_back=0` block events by `b.user` inside a derived table with the existing
`FORCE INDEX (type)`. Apply time/world bounds there. Join the reduced totals to `co_user`,
apply the central real-player predicate, and sum by normalized UUID. Both groups use
`ORDER BY NULL`; there is no placement exclusion, denominator ranking, total count, limit,
or per-player query. UUID/name validation is performed on user aggregates, not each block.
The natural-target SQL is unchanged and has no forced index.

The sync reader uses a bounded primary-key rowid batch, groups day/user/world/material
before the same player join, and stores compact day/normalized-UUID/world/stable-material
counts. Reconciliation uses the existing `type` index with one UTC day and a watermark cap.
All SQL stays in the repository, parameterized, under the existing read-only transaction
and three-second limits. No material/world IDs are hardcoded or stored as semantic material keys.

Report merging starts from natural miners, normalizes UUIDs, and attaches base counts.
PostgreSQL contributes no names. Existing live aggregate names may be historical; partial
boundary names retain the existing minimum-name merge behavior. Each layer independently
filters positive target counts and orders by target descending, name ascending, UUID ascending.
Decimal ratios use that layer's target/base values, display two decimals, and show a dash
for a zero divisor. A zero numerator is `0.00`. Small sample means fewer than 1,000 base
blocks in that layer; it is context, never a cheating accusation.

### Calendar and table behavior

The locally served vanilla `mining-range.js` progressively enhances the GET form without
dependencies, inline scripts, or CSP changes. A single modal calendar shows two months
on desktop and one on mobile. The first click chooses start, hover previews the range,
and the second click chooses end (reverse clicks are normalized). Apply range submits;
clicking dates alone does not run a query. Cancel/Escape discards draft edits and restores
focus. Arrow keys move by day/week, Home/End by week boundary, Page Up/Down by month.

Selecting September 10–12 sends September 10 00:00 UTC inclusive and September 13 00:00
UTC exclusive, including the entire final second of September 12. Adjust precise times
reveals human-readable Start time / End time controls opening a themed radial clock.
Whole-day end displays 23:59 with an end-of-day label but still sends next-day midnight.
An explicitly chosen end time is exclusive on the selected final date. Use end of day
restores the full final date. Start is inclusive. Clock edits use minute precision;
existing seconds, offsets, and subseconds remain unchanged unless that bound is edited.
With JavaScript unavailable, labelled UTC timestamp fields remain usable; their end is
always exclusive. Quick presets retain their existing bounds and clear custom inputs
when selected in the enhanced UI. All time is still the default and has no fixed cutoff.

Each statistics table uses a bounded `65vh` region with horizontal and vertical scrolling.
Header cells use `position: sticky; top: 0`, opaque theme backgrounds, and z-index 2.
The portal topbar is not fixed, so no viewport-header offset is needed inside this region.
Columns stay aligned during both scroll directions. The dashboard uses the existing green
primary button, labelled Open mining statistics.

### Read-only performance validation

Validate bounded batch and daily reconciliation queries on production MariaDB with the
SELECT-only account and existing limits. Local SQLite semantic fixtures cannot establish
MariaDB materialization plans or performance. For partial boundaries, the existing
`repo._aggregate_statement(query, ids, natural_only=False)` helper can build a narrow
query for `EXPLAIN`; resolve IDs dynamically from `DIAMONDS.denominator_materials` first.
Execute `EXPLAIN ` plus that fixed SQL with its original parameter tuple through
`repo._cursor()`. Inspect the inner `type` scan and outer primary-key user lookup.
Do not substitute `ANALYZE`, which executes the query. See the operational guide for
backfill, incremental, reconciliation, restart, and production concurrency validation.
No timeout increases or CoreProtect schema/index changes are authorized.

### Radial clock interaction

The locally served `mining-clock.js` is dependency-free and keeps existing CSP unchanged.
Its 24-hour face puts 1-12 on the outer ring and 13-23/00 on the inner ring. Choosing an
hour switches to minutes; every minute is selectable, with five-minute labels and a hand.
Mouse/touch taps select a dial position. The keyboard slider supports arrows, Home/End,
and Enter; hour/minute readout buttons switch faces. Both themes use portal colors.

Use time commits only to the calendar draft. Cancel/Escape leaves the prior time unchanged
and returns focus. Calendar Cancel discards committed clock drafts too. Only Apply range
submits analytics. The UI describes an explicit end as exclusive; choosing 23:59 explicitly
means 23:59:00 exclusive, while the separate End of day state includes the entire last minute.
The main GET form retains labelled plain timestamp inputs without JavaScript (or if clock
initialization is unavailable). ISO values remain internal to the enhanced picker, not its
normal displayed controls. Server validation remains authoritative.
