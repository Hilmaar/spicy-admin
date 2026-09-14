# CoreProtect: external, authoritative, read only

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

### Natural mining: required future business rule

A candidate counts only when it is a non-rolled-back break and there is **no earlier,
non-rolled-back player placement of the same material at the same world, x, y, and z**.
A placement after the break cannot retroactively invalidate that natural discovery.
Do not restrict placement lookup to the selected reporting window: a placement before
the window can still invalidate a break inside it. Same-second ordering needs explicit
validation against production timestamps/row ordering before future analytics ships.

Silk Touch/Fortune example: a player finds ore, mines it with Silk Touch, places it at
home, then breaks it with Fortune. The final break is not a second natural discovery.
Apply the exclusion to comparison materials too: demolishing player-placed stone must
not inflate the denominator of a diamond/stone ratio.

## Phase 1 implementation

`coreprotect/repository.py` defines the semantic protocol and MariaDB implementation:
`check_connection()`, `get_version()`, `list_worlds()`, `resolve_world(name)`, and
`resolve_material(name)`. A future backend can implement the protocol without changing views.
No analytics or block-event operations exist yet.

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
rollbacks. No CoreProtect data is copied into PostgreSQL.

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

## Future plans — not implemented

Rare-ore candidates can use `(type, time)`, with prior-placement checks using
`(wid, x, z, time)` and full y/material constraints. Verify plans with narrow, bounded
queries. Stone, deepslate, and netherrack may have millions of events: do not compute
global denominator ratios on each request. Never fetch unused blobs.

Later work may use a `co_block.rowid` watermark, compact derived PostgreSQL aggregates,
periodic processing, recent-event reconciliation, and a manual rebuild. Monotonic IDs
alone do not handle rollback changes to old rows; reconciliation is essential. Do not
copy the entire block table. Target/comparison groups must use material names and
dynamic worlds. Player pages could later reference `co_session`, `co_chat`, `co_command`,
`co_container`, and `co_item` through semantic services.

No workers, leaderboard, ratios, veins, suspicion scores, guilt judgements, live feed,
ClickHouse, DuckDB, or CoreProtect migration are implemented in Phase 1.

