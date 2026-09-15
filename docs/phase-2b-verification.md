# Phase 2B verification

Verified locally on 2026-09-15. No push, merge, deployment, production database access,
CoreProtect writes/schema changes, or host/infrastructure changes were performed.

## Results

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 136 tests passed: all 114 existing tests plus 22 Phase 2B tests |
| `ruff check .` | Passed |
| `ruff format --check .` | 58 Python files already formatted |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | All 13 templates passed formatting and lint |
| `git diff --check` | Passed; Git reports existing Windows line-ending notices |
| `python manage.py collectstatic --noinput` | Passed using production manifest/compression storage with local dummy settings |
| Local headless Edge harness | Passed Phase 1 regression and Phase 2B interaction/layout checks; no JavaScript errors |

The browser harness uses local SQLite, mocked Discord authorization, and synthetic target
and denominator results. It checks ratios, a long table's sticky header during both scroll
directions, quick/custom/world filters, hover preview, arrow/Enter selection, Cancel/Escape,
focus return, exact time entry, and no analytics requests from draft date clicks.

Date checks include September 10–12 mapping to September 13 midnight exclusive, a single
leap day, reverse selection spanning months, UTC offsets, and microsecond precision. These
run with the browser timezone set to Pacific/Honolulu. JavaScript-disabled form submission
also passes. Desktop dark/light and 320px/390px mobile layouts were checked; screenshots
and the existing local harness remain ignored under `.artifacts/`.

## Test changes

- `coreprotect/test_denominators.py`: 12 tests execute generated SELECTs on synthetic
  SQLite fixtures. They cover normal/deepslate base counts, invalid actors/actions,
  rollback exclusion, time/world bounds, complete end days, subsecond bounds, dynamic/missing
  mappings, UUID grouping, fixed query count, no denominator placement lookup, and a
  single-material fixture group. Placed base blocks count while placed diamonds remain excluded.
- `analytics/test_ratios.py`: 10 tests cover full UUID union, all formulas, zero divisors,
  deterministic ordering, small-sample boundaries, same-bound queries, complete-success
  caching, denominator failure, table/picker/dashboard markup, and authoritative validation.
- Existing analytics tests initialize the added denominator mock and assert the new cache
  namespace. Existing natural-mining tests share their fixture helper with denominator tests;
  all original natural-mining assertions remain intact.

## Implementation files

- CoreProtect: `coreprotect/mining.py`, `coreprotect/repository.py`, and SQL semantic tests.
- Analytics: `forms.py`, `services.py`, `views.py`, ratio template filters, and tests.
- UI: `templates/analytics/diamonds.html`, `range_picker.html`, `templates/base.html` script
  block, dashboard button, `static/js/mining-range.js`, and `static/css/portal.css`.
- Guidance: `AGENTS.md`, README, `docs/coreprotect.md`, and this record.

No dependencies, environment variables, migrations, permission rules, OAuth/CSP settings,
Docker/Compose files, proxy settings, or timeout values changed.

## Validation boundary

SQLite proves the query's relational semantics, not MariaDB 10.3 optimizer choices,
collation behavior, or production latency. Docker was not available locally. The production
schema/UUID conventions and same-second rowid ordering remain supplied assumptions.

The full uncached page performs five SELECTs: worlds, target mappings/aggregate, and base
mappings/aggregate. Both aggregates use one shared filter object but separate read-only
transactions. Concurrent source changes can occur between them. No partial report is
cached or shown on failure. Successful reports use 45-second per-process caching.

Before relying on broad/all-time production ratios, follow the
[read-only denominator EXPLAIN procedure](coreprotect.md#read-only-denominator-explain-and-performance-validation).
Check material mappings, known placed-base versus natural-target samples, the `(type,time)`
candidate index and user primary-key lookups, and representative timings within existing
limits. Do not automatically increase timeouts or add indexes/workers.

Phase 2C+ remains deferred: other ore pages, scores/alerts, player pages, live feeds,
integrations, background aggregation, rollups, and event copies.
