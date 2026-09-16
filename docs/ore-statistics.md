# Phase 2B.2 ore overview and material reports

The sidebar and dashboard mining action open `/ore-statistics/`. Its compact Diamonds,
Ancient Debris, and Emerald cards show all-time/all-world natural target block totals and
unique qualifying players. Diamond/Emerald players are the normalized-UUID union across
their two layers, never a sum of separate player counts. Cards query targets only: no
denominator scans, PostgreSQL rollup SUMs, or rollup readiness dependency. A failed card
shows unavailable instead of zero; successful cards remain usable. Results are cached for
45 seconds per process and include the query timestamp. These are block breaks, not drops.

The reusable Overview / Diamonds / Ancient Debris / Emerald navigation appears on every
section page. Links have visible labels and `aria-current="page"`. Existing Discord
authorization and revalidation protect every route, including cached results.

## Reports and semantics

| Route | Table order | Target / denominator |
| --- | --- | --- |
| `/ore-statistics/diamonds/` | Deepslate Diamond Mining, Normal Diamond Mining | deepslate diamond ore / deepslate; diamond ore / stone |
| `/ore-statistics/ancient-debris/` | Ancient Debris Mining | ancient debris / netherrack |
| `/ore-statistics/emerald/` | Deepslate Emerald Mining, Normal Emerald Mining | deepslate emerald ore / deepslate; emerald ore / stone |

All target names resolve dynamically through CoreProtect's material map. Every target
uses the existing strict natural-ore SQL: unrolled break by a real player, with no earlier
unrolled player placement of the same material at the same world/x/y/z. Same-second ties
use rowid, and historical placements are not limited by the reporting start. No new query
semantics, index hints for targets, CoreProtect writes, or timeout increases are introduced.

All three denominator materials count qualifying player breaks including previously
placed blocks. Netherrack joins `ROLLUP_MATERIALS` as a stable material key in the existing
daily rollup. No new PostgreSQL schema or second sync/freshness architecture is needed.
The existing batch watermark, lock, recent rollback reconciliation, and full rebuild apply
to all three materials. See [rollup operations](mining-rollups.md).

All Time remains the default on every detail page and never queries live denominators.
Whole UTC days come from PostgreSQL; precise boundaries use at most two disjoint live
windows shorter than 24 hours, with the selected group's material names. The shared
calendar/radial clock, UTC inclusive start/exclusive end, world filter, Cancel behavior,
and plain-input fallback are unchanged. Tables include only positive natural miners in
their own layer; base-only players never create visible rows.

Every table shows Player, target blocks, corresponding base blocks, `target / base * 1000`,
and `base / target`. For Ancient Debris these are Ancient Debris per 1,000 Netherrack and
Netherrack per Ancient Debris. Emerald uses Emeralds per 1,000 Stone/Deepslate and the
corresponding inverse. Ratios retain two-decimal display; zero divisors show a dash.

## Sorting and independent sample thresholds

All five headers have keyboard-operable buttons. Click/Enter/Space selects a sort and
repeats reverse it. New numeric sorts start descending; Player starts ascending. Arrows
and `aria-sort` expose the active direction; a polite status announces changes. Header
cells remain sticky in each independently scrollable table.

The default is **targets per 1,000 corresponding base blocks, descending**. At every sort
column/direction, reliable samples precede small samples; each partition sorts using the
same choice. Missing ratios sort last within their partition, in either direction. Ties
use case-insensitive name, exact name, then normalized UUID ascending. Counts compare as
integers and ratios as exact fractions (Python Fraction / JavaScript BigInt cross-products),
not rounded display strings. No rows or raw values are changed or hidden by sorting.

Each table has a labelled Minimum sample dropdown with exactly these options:
**250, 500, 1000, 2500, 5000, 10000**. A row is small when its corresponding base count is
strictly below the selected value. Changing it updates only the badge, muted ratio styling,
and reliable-before-small ordering, without submitting the form or requesting new data.

`analytics/ore_config.py` defines each table's `default_threshold`. All five currently
default to **1000**, but any table can independently choose another allowed default.
The server supplies the options/default to the generic JavaScript; there is no JavaScript
constant fixing every table at 1000. Without JavaScript, the server default, badge, and
deterministic ratio ordering remain usable; enhancement-only controls are hidden/disabled.

Browser LocalStorage persists only the threshold, under stable independent keys:

```text
spicy:mining:threshold:v1:deepslate-diamonds
spicy:mining:threshold:v1:normal-diamonds
spicy:mining:threshold:v1:ancient-debris
spicy:mining:threshold:v1:deepslate-emerald
spicy:mining:threshold:v1:normal-emerald
```

Preferences belong to that browser/origin, not the Discord account or query filters.
Invalid/absent values use the configured default; blocked storage still permits changes
for the current page. Sort choice resets to ratio descending on navigation. Thresholds
are neither server query parameters nor additional report cache variants.

## Material themes and optional local assets

CSS gives Diamonds cyan accents, Ancient Debris a muted reddish-brown metallic accent,
and Emerald green accents. Cards have slight background tints; tabs use borders/current
state. Light mode uses darker accents for readability. Visible material text remains the
identifier; decorative CSS gems and optional images are hidden from screen readers.

The UI requires no image files. `OrePage.image` is an optional local static path; leave it
empty to use the complete CSS fallback. Optional filenames that may be added later are
`static/img/materials/diamonds.webp`, `ancient-debris.webp`, and `emerald.webp`. After adding
an asset, set its page's `image="img/materials/<filename>"` and collect static assets.
Never point this field at an external URL or enable a filename before the asset exists.
No image hotlinks, textures, new runtime packages, or framework dependencies are introduced.

## Adding a future group after separate authorization

1. Add an `OreGroup` in `coreprotect/mining.py`, containing the slug and namespaced target
   and distinct denominator material names in stable order. Never supply numeric IDs.
2. Add a corresponding `OrePage` in `analytics/ore_config.py`: labels, title, optional local
   asset, and ordered `TableConfig` entries. Each table supplies a globally unique stable
   key, title, target/base tuple indices, column/ratio labels, and allowed default threshold.
   The key also identifies the browser preference; do not reuse another table's key.
3. Add its `material-<slug>` CSS theme. The catalog generates the detail route, overview
   card, and navigation; the shared detail template/table behavior need no duplication.
4. If a new denominator is required, extend `ROLLUP_MATERIALS` and plan a full rebuild.
   Existing shared Stone/Deepslate denominators need no new data model or sync pipeline.
5. Add strict source semantic tests, ratio/filter/membership/cache tests, and browser
   sort/threshold/theme coverage. Validate actual MariaDB plans and counts before use.

## Cache, freshness, and upgrading from Phase 2B.1

Detailed report keys now include material group, range, canonical custom bounds, world,
and sync generation (`mining:v5`). Overview keys are group-specific all-time target-only
keys. Successful results keep the 45-second TTL. Readiness/hard expiry are checked before
detail-cache access. Freshness still warns after 15 minutes or a failed sync and blocks
ratios after 24 hours; no incomplete rollup is presented as complete.

**Adding Netherrack changes the rollup material signature. Existing Phase 2B.1 detail
reports will show initialization until a reviewed full rebuild completes.** An ordinary
incremental run cannot backfill historical Netherrack and will request a full rebuild.
The overview does not depend on this readiness state.

For a later authorized release, back up portal PostgreSQL and follow the existing release
workflow. No new migration is generated for Phase 2B.2, but verify Phase 2B.1 migrations
are applied. With the updated image, run:

```bash
docker-compose run --rm web python manage.py sync_mining_analytics --full-rebuild
docker-compose run --rm web python manage.py sync_mining_analytics
```

The first command rebuilds all configured denominator history; the second catches up new
rows. If interrupted, resume using the ordinary command, not `--full-rebuild` again.
The existing recommended five-minute cadence remains; no scheduler is created here.

Production checks still needed: verify dynamic new material mappings, known natural and
placed/rolled-back samples, Netherrack backfill/reconciliation, actual MariaDB plans and
timings under the unchanged limits, PostgreSQL restart/concurrency behavior, and detail
filters/freshness/permissions. Broader target groups may cost more than diamonds; a timeout
must remain an unavailable result, not approximation or a timeout increase.

Iron/Coal/Gold/Redstone/Lapis/Copper pages, scores, alerts, feeds, integrations, raw event
copies, Redis/Celery, source schema/index changes, and infrastructure remain deferred.
No push, merge, or deployment is performed by this implementation.
