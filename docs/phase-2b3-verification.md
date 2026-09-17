# Phase 2B.3 verification

Implemented on `phase-2b-mining-ratios`: mining UI cleanup, configured ore worlds, overflow
affordances, the Admin audit log, and the requested environment-based Discord user-ID staff
override. No push, merge, deployment, infrastructure modification, CoreProtect schema/index
change, or timeout increase was performed. Phase 2C and other later features remain deferred.

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 225 tests passed |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; all files formatted |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | 19 templates; no formatting or lint errors |
| `git diff --check` | Passed |
| Static collection | Production WhiteNoise compressed manifest backend; 30 files post-processed locally |
| `python scripts/check_browser.py` | Full headless Edge regression plus Phase 2B.3 coverage passed |
| Production `check --deploy` with dummy local settings | Only existing expected HSTS warnings W005/W021 |

The Python suite retains the source SQL contracts/semantics, daily rollups, readiness,
normalized-UUID merges, cache/revalidation, sorting, and exact UTC tests. New coverage includes:

- Default-empty, one/multiple IDs, whitespace/empty entries, duplicate normalization,
  malformed IDs, and a fresh settings-import process proving invalid override config fails.
- Ordinary Admin/Overlord permissions; staff-only override for non-members and members
  without roles; unchanged role union, inactive/anonymous/other-user denials, API outage,
  immediate removal from active settings, and mandatory OAuth/state verification.
- Override-versus-role authorization metadata without the configured list or OAuth secrets.
- Admin-only audit list/detail/JSON/navigation, write-only staff threshold authorization,
  CSRF, exact keys/types/options, invalid events/payloads, and database-failure behavior.
- Structured authentication/denial/logout/page/filter events; retained actor snapshots;
  bounded request data, explicit query/metadata sanitization and conservative proxy trust.
- All audit presets, subsecond current events, precise inclusive/exclusive bounds,
  actor/type/result combinations, page sizes/order/links, empty states, and escaped details.
- Append-only model APIs, 365-day pruning, configurable retention, strict cutoff and
  idempotence; no retention runs on requests.
- Dynamic configured worlds for every group, ignored client world values, missing or
  ambiguous maps failing safely, cache identity changes, removed report copy, and safeguards.

The existing browser harness uses mocked Discord/CoreProtect, test settings, disposable
SQLite under ignored `.artifacts/`, and a loopback server. Its new
`scripts/audit_browser_checks.py` verifies:

- Admin audit navigation and real Overlord denial; server pagination/filter persistence;
  keyboard/row-click modal opening, escaped text rendering, Escape/Close focus return;
  shared calendar/clock, date draft cancellation and no-JavaScript detail/input fallback.
- One CSRF-protected threshold POST with exact old/new/table values; no POST on sort;
  preferences persisting after simulated audit network failure.
- Conditional top/bottom/left/right fades at scroll limits, no fades on a short table,
  sticky headers, resize/mobile overflow, removed world/status/helper UI, both themes.
- All prior Phase 1, ore overview/cards/tabs, sorting oracle, independent threshold storage,
  rollup unavailable state, UTC calendar/radial clock, keyboard/touch and non-JS checks.

No unexpected browser errors occurred. Inspected dark audit detail and light mining report
screenshots are readable. Browser screenshots are local artifacts, not committed assets.
The Windows sandbox blocked subprocess pipes for Playwright/djlint; those local checks ran
with the required process permission. No production connection was used.

## Migration and production boundary

`auditlog/migrations/0001_initial.py` adds the portal-owned `AuditEvent` model and four
indexes for newest order and actor/type/result filtering. It was applied only to local test
databases. Apply it before a future authorized release serves audit routes. There is no
Phase 2B.2 rollup rebuild requirement and no migration for allowlist changes.

Real PostgreSQL migration/index performance and retention volume, MariaDB mappings/counts,
Discord OAuth/role revocation and override changes across all workers, proxy socket/XFF
behavior, and legacy Compose/Nginx/TLS operation still need production validation. SQLite
and mocked services do not prove those deployment properties. Only explicitly verified
proxy peers should be configured for forwarded IP capture.

See [audit schema, events, privacy, permissions, overrides and operations](audit-log.md) and
[current ore/world/UI behavior](ore-statistics.md). A daily pruning schedule is recommended
but not installed. No event exports, editing, alerts, new ores, or later-phase work was added.
