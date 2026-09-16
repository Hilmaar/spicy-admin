# Phase 2B.2 verification

Implemented locally on `phase-2b-mining-ratios`, preserving the Phase 2B.1 query and sync
foundation. No push, merge, deployment, infrastructure change, CoreProtect schema/index
change, or timeout increase was performed. No PostgreSQL schema migration is required.

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 187 tests passed |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; all files formatted |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | 16 templates, no changes or lint errors |
| `git diff --check` | Passed |
| Static collection | Production WhiteNoise compressed manifest storage with dummy local settings; 22 files post-processed |
| `python scripts/check_browser.py` | Headless Edge regression and new material/sorting checks passed |

New Python coverage includes dynamic Ancient Debris/Emerald material mappings, strict
natural exclusion with historical and same-second placements, rolled targets and placers,
real-player filtering, precise time/world filtering, placed Netherrack denominator breaks,
Netherrack backfill/incremental/reconciliation/rebuild, target-only row membership, group
cache isolation, ratio formulas, Emerald layer separation/order, overview union player
counts, target-only overview reads, source failure recovery, every new route's permissions,
shared bootstrap safeguards, configurable defaults, and deterministic sample/ratio ordering.
Existing sync atomicity/restart/locking, freshness, authorization, and UTC tests still pass.

The browser suite retains the Phase 1 and calendar/clock checks and adds
`scripts/mining_browser_checks.py`. It checks:

- all five sortable columns in both directions against an independent exact-fraction oracle;
- keyboard Enter/Space, `aria-sort`, deterministic ties, missing ratios, and small samples last;
- exact dropdown options, default values, independent table keys, persistence across reloads
  and material navigation, invalid/blocked storage handling, immediate badge/style/order
  updates, unchanged cell values, and no source calls from threshold/sort actions;
- overview cards, material themes/tabs/links, Deepslate-first Diamonds/Emerald, the Ancient
  Debris table, both themes, 320px mobile layouts, and independently sticky headers;
- existing hover/keyboard/whole-date/precise UTC range selection, radial clock touch/keyboard,
  Cancel behavior, non-JavaScript fallback, and rollup-not-ready screen.

The harness uses mocked CoreProtect/Discord, dummy Django settings, an ignored local SQLite
database, and a loopback-only server. Screenshots under `.artifacts/` use reduced-motion
mode to capture settled theme colors; inspected overview/detail screenshots are readable
in both themes without image assets. No unexpected browser errors occurred. Playwright and
Microsoft Edge remain optional local verification tools, not new runtime dependencies.

Local SQLite relational tests and SQL contract assertions do not establish MariaDB plans,
collation, actual production performance, or PostgreSQL multi-process transaction behavior.
Production validation still requires known source samples and query plans/timings for the
new targets and Netherrack, plus the existing rollup restart/concurrency checks.

**Upgrade requirement:** Netherrack changes the material signature. A later authorized
release must run a full rollup rebuild, then a normal catch-up sync. Until initialized,
detail ratios are unavailable; target-only overview cards remain usable. No rebuild was
run against production. See [the Phase 2B.2 operating guide](ore-statistics.md).
