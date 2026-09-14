# Phase 2A verification

Verified locally on 2026-09-14. No push, merge, deployment, production database access,
or host/infrastructure changes were performed.

## Completed checks

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 114 tests passed, including the existing 53 Phase 1 tests |
| `ruff check .` | Passed |
| `ruff format --check .` | 53 Python files already formatted |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | 12 templates passed formatting and lint |
| `python manage.py collectstatic --noinput` | Passed with production manifest/compression storage and local dummy settings |
| `git diff --check` | Passed; only Git's existing Windows line-ending notices |
| Local headless Edge checks | Phase 1 regression, diamond navigation/counts, quick/custom/world forms, dark/light themes, 320px/390px layouts, table scrolling, logout; no JavaScript errors |

The browser checks used mocked Discord membership and synthetic diamond results. Screenshots
and the local harness are ignored under `.artifacts/`; they are not runtime dependencies.
Two existing sign-out buttons now explicitly use `type="submit"` to satisfy template lint.
An existing CSP string received indentation-only Python formatting.

## Automated test coverage

`coreprotect/test_mining.py` adds 27 tests. These execute the repository's generated SELECTs
against small in-memory SQLite fixtures, translating only placeholders and `STRAIGHT_JOIN`
and providing a REGEXP shim. They cover every required mining case, Silk Touch/Fortune,
rolled-back and non-player placements, UUID grouping, ordering, material/world resolution,
time boundaries, and read-only connection cleanup/timeout behavior using a driver double.

`analytics/tests.py` adds 34 tests covering permission enforcement and role revocation,
validated UTC filters, dynamic worlds, equivalent/distinct cache keys, cache expiry/failure,
original cached timestamps, escaped names, safe external failure, distinct empty reports,
and navigation. Tests never require production credentials or a real CoreProtect server.

## Remaining production validation

MariaDB 10.3 execution plans, production collation/UUID conventions, and latency on the
actual event history have not been measured. SQLite semantic tests do not establish them.
Existing Docker Compose, PostgreSQL, Nginx, Certbot, OAuth configuration, dependencies,
timeouts, and environment variables are unchanged. Docker was unavailable locally, so
container runtime compatibility was not independently rerun for this change.

Use the read-only steps in [CoreProtect production validation](coreprotect.md#production-validation-before-broad-use):

1. Verify both material mappings and representative player/pseudo-user UUID records.
2. Review `EXPLAIN` for a narrow range/world using the existing SELECT-only account.
   Expect candidate access through `(type,time)` and placement access through `(wid,x,z,time)`.
3. Compare known natural breaks and Silk Touch re-breaks, including same-second events and
   placements older than the reporting window. Validate the `(time,rowid)` ordering assumption.
4. Exercise all filters, then all-time performance within the existing timeout. Do not
   interpret an unavailable response as an empty result or automatically raise timeouts.
5. Verify Admin/Overlord access, Patron/member denial, and revocation with a warm cache.
   Test external failure in an isolated environment while checking other portal pages.

Phase 2B and later features remain unimplemented: denominator counts/ratios, other ores,
scoring/alerts, player pages, live activity, background workers, and event copies.
