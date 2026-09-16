# Phase 2B.1 verification

Implemented on `phase-2b-mining-ratios`. No push, merge, deployment, infrastructure change,
CoreProtect schema/index change, or timeout increase was performed.

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 174 tests passed |
| `ruff check .` | Passed |
| `ruff format --check .` | 75 Python files formatted |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | 14 templates, no formatting changes or lint errors |
| `git diff --check` | Passed (existing Windows line-ending notices only) |
| Static collection | Passed with production WhiteNoise compressed manifest storage and dummy local settings; 19 files post-processed |
| `python scripts/check_browser.py` | Local headless Edge checks passed; no unexpected browser errors |

The browser harness is now tracked and repeatable. It requires Playwright installed in a
local development environment and Microsoft Edge; neither is a new runtime dependency.
It creates only `.artifacts/ui.sqlite3`, uses dummy Django test settings, binds a loopback
server, mocks external services, and writes ignored screenshots under `.artifacts/`.
It covers Phase 1 login/dashboard/navigation/docs, both five-column tables, zero All Time
live denominator calls, both independently sticky headers, desktop dark/light, 320/390px
mobile, UTC calendar hover/keyboard/Cancel, radial clock keyboard/touch/Cancel, exact and
whole-date bounds, non-JavaScript fallback, and the rollup-not-ready screen. The latter
injects an unavailable snapshot; actual missing/uninitialized database states are separately
covered by request/service tests. No production system is contacted.

New database and SQL tests cover daily uniqueness/dimensions; dynamic materials; normalized
UUIDs; real-player/actions/rollback semantics; UTC boundaries; primary-key batch gaps;
captured high-water resume; incremental idempotence; atomic counts/watermark commit failure;
recent replacement and old history/full rebuild; failed reconciliation; watermark caps;
source shrink; overlapping-run exclusion; PostgreSQL advisory-lock SQL/release contracts;
All Time/whole-day/hybrid coverage; generation invalidation; freshness/bootstrap/errors;
layer membership, ordering, formulas, zero divisors, and separate small-sample thresholds.

Local SQL fixtures translate MariaDB SELECT syntax for SQLite execution. They establish
relational semantics and SQL contracts, **not** MariaDB plans, production timings, collation,
transaction behavior, or PostgreSQL multi-process locking. No local PostgreSQL/MariaDB or
Docker runtime validation was available. The runtime migration is generated but has not
been applied to production. Follow [the operations guide](mining-rollups.md) for the later
authorized migration/backfill sequence, source sample/plan checks, PostgreSQL concurrent
sync/restart validation, manual catch-up, and future five-minute scheduler setup.
