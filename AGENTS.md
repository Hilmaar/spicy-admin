# spicy-admin invariants

Phase 1, Phase 2A, and Phase 2B.3 (mining UI cleanup, audit log, and Discord user-ID staff overrides) are implemented. Do not implement Phase 2C
or later scope unless explicitly asked.

1. **CoreProtect is READ ONLY.** Never write data, change schema/indexes, run migrations,
   or perform rollbacks against it. Production credentials must have SELECT-only access.
2. Never hardcode numeric CoreProtect material IDs. Resolve names through `co_material_map`.
3. Never hardcode numeric world IDs. Resolve names through `co_world`.
4. Target ores must exclude player-placed blocks. Phase 2B.2 stone/deepslate/netherrack denominators
   intentionally count all qualifying player breaks, including previously placed blocks.
   Never add historical placement exclusion to these denominator queries.
5. Only an earlier non-rolled-back player placement of the same material at the same
    world/x/y/z invalidates a candidate break. A later placement must not invalidate it.
    Use `(time, rowid)` ordering, with rowid breaking same-second ties. Search placements
    before the reporting window too; time/world report filters apply to candidate breaks.
6. Rolled-back events do not count. `action=0` means break; `action=1` means placement.
7. Discord OAuth remains mandatory. Exact role IDs or owner-configured Discord user IDs grant access.
   The environment allowlist grants only Minecraft staff permissions, never Admin permissions.
8. Revalidate membership/roles server-side every 30-60 seconds; fail closed on API errors
   for ordinary users. Explicit user-ID overrides do not depend on guild membership or role checks.
9. Production uses standalone **`docker-compose` 1.25.0**, not Compose v2. Keep version 3.7
   YAML and legacy commands. Avoid profiles, modern depends_on conditions, and newer syntax.
10. Never alter existing Docker/Pterodactyl/Wings infrastructure, daemon configuration,
    networks, containerd, or host package versions. Use project-owned resources only.
11. Nginx and Certbot run on the host. No proxy/certificate containers or automated host edits.
12. Dark mode is the default; preserve accessible light mode and responsive navigation.
13. The primary accent is **`#00fb9a`**, with neutral dark backgrounds near `#242424`.
14. Do not push, merge, or deploy unless the user explicitly requests it.

## Structure and checks

- `accounts`: OAuth and a single centralized permission service; no password backend.
- `portal`: dashboard/layout; `documentation`: sanitized, allowlisted repository Markdown.
- `coreprotect`: semantic repository boundary, no Django-managed external models.
- `analytics`: validated UTC ore filters, short result caching, and protected UI.
- `auditlog`: centralized bounded append-only writes and Admin-only history; read docs/audit-log.md.
- Only Admin roles grant `portal.audit_log` and `portal.configure`. Never expose the override list.
- Audit secrets are excluded explicitly; threshold writes require analytics permission and CSRF.
- Current ore pages resolve logical worlds from the catalog (world/world_nether), never user input.
- Centralize breaker/placer classification: non-empty non-# name and well-formed non-nil
  UUID. Group diamond results by normalized UUID; do not assume every co_user row is a player.
- Cache hits must never bypass `minecraft.analytics` authorization or Discord revalidation.
- Merge target/base aggregates by normalized UUID using identical time/world query bounds;
  cache only complete successful reports. Display only players with positive natural-target
  totals; denominator-only players never create report rows.
- Live boundary/reconciliation denominator queries use FORCE INDEX (`type`); rowid batches
  use PRIMARY. These are existing CoreProtect indexes; natural
  target queries retain their original index selection. All time remains the default.
- Denominators aggregate block events by `b.user` before joining/filtering `co_user`, then
  combine counts by normalized UUID. Do not restore per-block UUID/REGEXP checks or totals/sorts.
- Calendar whole-day selections send next-day midnight as exclusive end; precise times
  retain inclusive-start/exclusive-end semantics. Server validation remains authoritative.
- The radial clock edits calendar drafts only. Whole-day end remains next-day midnight;
  explicitly chosen end times are exclusive. Clock Cancel and calendar Cancel discard their drafts.
- Denominators use portal PostgreSQL daily rollups; only partial boundaries shorter than
  24h may query CoreProtect during reports. All Time never falls back to a live base scan.
- Sync uses a PostgreSQL advisory lock, atomic batch/watermark commits, and recent UTC-day
  replacement capped at the committed watermark. Read docs/mining-rollups.md before changes.
- Show only positive natural miners in each independently sorted layer table.
- Diamonds, Ancient Debris, and Emerald share the ore catalog and detail table component.
- Read docs/ore-statistics.md for catalog, sorting, threshold, and upgrade behavior.
- Default table ordering is ratio descending, small samples always last. Per-table thresholds
  persist independently in the browser; options are 250/500/1000/2500/5000/10000, default 1000.
- Further ore pages, scores, worker frameworks, and raw event copies remain out of scope.
- Only PostgreSQL belongs in runtime `DATABASES`; SQLite is isolated to automated tests.
- Never log tokens, secrets, API payloads, or OAuth callback query strings.
- Run `python manage.py test --settings=config.settings.test`, `ruff check .`, and
  `ruff format --check .` in the project environment. Prefer documented Docker equivalents.
- Keep migrations synchronized using `makemigrations --check --dry-run` with test settings.
- Keep `.env.example` and the README environment table synchronized with settings.
- Read `docs/coreprotect.md` before changing the external-data boundary or planning analytics.
