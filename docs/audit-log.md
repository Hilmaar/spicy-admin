# Phase 2B.3 audit log and access overrides

The portal records meaningful staff activity in its own PostgreSQL database. This is an
application audit trail, not Nginx access-log ingestion. The new `auditlog` app and
`auditlog/0001_initial` migration add `AuditEvent`; CoreProtect is unchanged and read-only.

## Access

`portal.audit_log` belongs only to the configured Discord Admin role, alongside
`portal.configure`. Minecraft Overlord has neither permission. The Audit Log sidebar link,
`/audit-log/`, `/audit-log/<id>/`, and its `?format=json` detail response all check the same
central permission service on every request, with the existing role revalidation rules.
There is no event editing/deletion UI, export, public history endpoint, or Django admin.

The separate write-only `/audit/client-event/` endpoint requires `minecraft.analytics`:
staff can record their own threshold changes without gaining permission to read history.

## Discord user-ID override

`DISCORD_ACCESS_OVERRIDE_USER_IDS` is an optional owner-controlled, comma-separated
environment value; empty by default. Copy Discord **user IDs**, not names or role IDs.
`accounts.configuration.parse_access_override_ids` trims whitespace, ignores empty entries,
deduplicates, and rejects noncanonical/non-ASCII/non-numeric/zero/out-of-range uint64 values.
Invalid configuration raises `ImproperlyConfigured` during settings import without echoing
the values. No actual user IDs are shipped in application configuration.

An active portal user must still authenticate through the normal Discord OAuth callback,
including session-bound state and profile verification. An exact allowlist match grants
the Minecraft Overlord staff set: `portal.access`, `minecraft.analytics`, and
`minecraft.punishments`. It requires neither guild membership nor a matching guild role,
and remains valid if the membership API is unavailable. It grants **neither**
`portal.configure` **nor** `portal.audit_log`. Verified role permissions combine with this
set, so an allowlisted Admin still receives normal Admin access.

The list is checked in `authorization_for` on every protected request. It is never copied
into the database, session, frontend, diagnostic response, or audit metadata. Ordinary
users retain the same membership cache, revocation, and fail-closed behavior. Removing an
ID from active settings takes effect at the next authorization check, without waiting for
role cache expiry. Deployment environment changes must first be loaded by all application
workers through the normal release/recreation process; editing `.env` alone cannot change
the environment of running containers. No migration is needed for allowlist changes.
There is no self-enrollment or management UI.

Successful authorization records `authorization_source: "user_override"` when the override
grants otherwise unavailable access, or `"discord_role"` when roles already grant access.
This records the source for that actor, not the configured list. An override-granted login
is a successful authentication, never a denied-role event.

## Stored schema and events

Each event stores a UTC timestamp, structured event type/result, nullable actor Discord ID,
display-name/username snapshots, method/path/sanitized query, IP, bounded User-Agent,
sanitized Referer, host, Accept-Language, and allowlisted JSON metadata. Actor snapshots
survive renames and account deletion. Unknown callback identities remain null.
Result categories are `success`, `denied`, `error`, and `info`.

| Event type | Trigger |
| --- | --- |
| `auth.discord.succeeded` | Verified, authorized Discord callback |
| `auth.discord.denied` | Invalid/expired state, OAuth failure, inactive account, missing role or guild |
| `auth.logout` | Authenticated logout, before session removal |
| `page.dashboard.viewed` | Dashboard GET |
| `page.code_of_conduct.viewed` | Code of Conduct GET |
| `page.ore_overview.viewed` | Ore overview GET |
| `analytics.diamonds.viewed` | Diamond report GET |
| `analytics.ancient_debris.viewed` | Ancient Debris report GET |
| `analytics.emerald.viewed` | Emerald report GET |
| `analytics.filtered` | Successful report GET with explicit range/bounds |
| `analytics.threshold_changed` | Validated staff threshold POST |

Report metadata includes ore group, configured logical world, preset, effective UTC bounds
when bounded, and validated current table thresholds when supplied by the browser. Cached
reports retain the effective bounds of the original query. Page reloads/bookmarked filter
URLs also produce filtered events. Assets, health checks, audit reads, incidental requests,
and sort clicks do not produce page events. Failed source reads record an error result.

All application inserts go through `auditlog.service.record`. It bounds strings and
allowlists query keys and event-specific metadata. **Cookies, Authorization headers,
session IDs, CSRF tokens, OAuth codes/state/access/refresh tokens, arbitrary headers/forms,
and unknown query/metadata keys are not copied.** Referers retain only origin and path;
credentials, query, and fragment are removed. Database insertion failures emit a fixed
server-side error without exception/SQL details, isolate the insert with a savepoint, and
preserve the primary page/authentication outcome. There is no recursive audit logging.

Model saves/queryset updates and ordinary deletes reject historical mutations. Retention
is the sole application deletion path. This is application-level append-only behavior,
not a tamper-proof database ledger. Indexes support newest-first order and actor/type/result
filters: descending timestamp/id, plus actor+timestamp, type+timestamp, result+timestamp.
These indexes are exclusively on portal PostgreSQL.

## Client IP and proxy trust

By default record the validated socket peer (`REMOTE_ADDR`). Ignore forwarded headers.
`AUDIT_TRUSTED_PROXY_IPS` can explicitly list exact trusted peer addresses. Only when the
socket peer matches will a **single valid IP** from `X-Forwarded-For` replace it; invalid
values/chains fall back to the peer. There is no blanket trust of private ranges or public
forwarded headers. The existing host Nginx example overwrites XFF with `$remote_addr`.

Before configuring this optional list, verify the actual peer Django sees through the
loopback Docker mapping and that this path can only originate at the trusted proxy. Leave
empty if uncertain: a proxy/bridge IP is preferable to an attacker-controlled address.
No Nginx, Docker, networking, or infrastructure configuration is changed by this feature.

In the deployment reported for Phase 2B.4, the web container sees the host/Docker bridge
peer `172.26.0.1`. Production explicitly configures `AUDIT_TRUSTED_PROXY_IPS=172.26.0.1`
because host Nginx overwrites both `X-Real-IP` and `X-Forwarded-For` with `$remote_addr`.
The app still uses the single validated XFF value only after checking that exact peer.
This is a deployment-specific setting, not a hardcoded or default trusted address.
Other deployments must verify their own peer/path. Historical audit rows containing
`172.26.0.1` remain unchanged; no backfill or database migration is needed.

## Browsing and threshold events

The audit table contains only Timestamp / Actor / Event / Result, newest first. It defaults
to Last 7 days, supports 24h/30d/All time/Custom, and reuses the mining UTC calendar and
radial clock. Inclusive-start/exclusive-end, Cancel, keyboard/touch, and non-JS inputs
remain unchanged. Actor, event type, and result filters run server-side. Pagination loads
100 events by default, optionally 50, preserving filters and page size in links.

Click a row or activate its event link to open the accessible detail modal. Escape/Close
returns focus to the event link. It fetches the Admin-protected detail endpoint and builds
text nodes; JSON is never treated as HTML. Without JavaScript the link opens a normal
escaped detail page. IP/User-Agent/request metadata appear only in details.

Threshold writes must be CSRF-protected JSON POSTs with exactly `event_type`, `table`,
`old_threshold`, and `new_threshold`. The type must be `analytics.threshold_changed`, the
table must be a known stable key, and distinct old/new values must be integers from
250/500/1000/2500/5000/10000. Arbitrary metadata/types/keys, strings, booleans and equal
values are rejected. The actor always comes from the session. These client-reported
preferences are informational, not authoritative mining data. UI updates and LocalStorage
persistence happen independently of POST success. Sorting never submits an audit event.

## Retention and operations

`AUDIT_LOG_RETENTION_DAYS=365` by default. The following command deletes only events
strictly older than that cutoff, reports its count, and is safe to repeat:

```sh
docker-compose run --rm web python manage.py prune_audit_logs
```

Recommend a once-daily run using the operator's existing scheduling system, with output
monitored. Daily describes execution frequency, not retention duration: each run deletes
only rows older than 365 days (or the configured duration), retaining a rolling 365-day
history. Recent events are retained. No scheduler is installed and no pruning happens on page requests.

For a later authorized release, apply portal migrations before serving the new code:
`docker-compose run --rm web python manage.py migrate`. The existing startup script also
applies migrations. This phase requires no rollup rebuild when upgrading from working
Phase 2B.2. Validate real PostgreSQL migration/indexes/retention, proxy identity, Discord
permissions and override removal under the deployment's worker configuration. No deployment
or production cleanup has been performed here.

Future audit events should add a structured `EventType`/friendly label, explicit bounded
metadata handling in the central service, a narrow hook at the meaningful action, and
permission/sanitization/failure tests. Never feed arbitrary client event types or payloads
into storage. New ore groups, investigations, punishments, alerts, export, full-text search,
external analytics platforms, and later phases remain deferred.
