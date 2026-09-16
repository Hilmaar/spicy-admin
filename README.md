# spicy-admin

Private staff portal for **spicy.is**, intended for `https://admin.spicy.is`.
Phase 1 includes Discord login, current-role authorization, a responsive dark/light dashboard,
documentation placeholders, and read-only CoreProtect diagnostics. Phase 2A adds natural
diamond mining counts with time/world filters. Phase 2B adds stone/deepslate mining ratios
and a themed date-range picker. Phase 2B.1 adds PostgreSQL daily denominator rollups
and separate normal/deepslate tables. Phase 2B.2 adds an ore overview, sortable tables,
independent sample thresholds, Ancient Debris, and Emerald. Further ores, live activity,
player investigations, punishments, and integrations remain future scope.

## Architecture

```text
Browser → host Nginx / HTTPS → 127.0.0.1:8086 → web (Django + Gunicorn)
                                                  ├─ postgres (portal state + daily rollups)
                                                  ├─ Discord HTTPS API (identity + roles)
                                                  └─ host MariaDB (CoreProtect, SELECT-only)
```

- Python 3.12, Django 5.2 LTS, server-rendered templates, small vanilla JavaScript,
  handwritten CSS, and WhiteNoise static delivery. No frontend build or API tier is needed.
  Django 5.2 is an [LTS release](https://www.djangoproject.com/weblog/2025/apr/02/django-52-released/).
- PostgreSQL 16 stores users, sessions, daily mining rollups, and shared authorization state. Role results expire
  after 45 seconds by default, including across Gunicorn workers. Revocation takes effect
  on the next protected request after expiry; already-rendered content is not remotely erased.
- Discord OAuth uses `identify`; a bot credential fetches individual guild membership for
  revalidation. User access tokens are discarded after profile lookup. Admin has portal and
  configuration permissions; Minecraft Overlord has ordinary Minecraft portal permissions.
  Patron and ordinary membership grant no Phase 1 access.
- PyMySQL reads CoreProtect through a semantic adapter and READ ONLY transactions.
  The old MariaDB server is outside Django's database configuration.
- Markdown uses an explicit page registry and HTML sanitizer. No CMS or arbitrary paths.
- No local passwords, Django admin login, superuser bypass, or development login shortcut.

```text
accounts/                    Discord OAuth, users, permissions, authorization cache, tests
config/                      Django settings, URLs, WSGI
portal/                      Dashboard, security headers, DB readiness command
documentation/               Safe Markdown rendering and tests
coreprotect/                 Read-only adapter, diagnostics, mocked tests
analytics/                   Diamond filters, short-lived result cache, protected page
content/{conduct,commands,pterodactyl}/
templates/                   Layouts, reusable components, portal pages
static/                      CSS, theme/menu scripts, SVG icons
deploy/                      Startup scripts, Gunicorn, manual host Nginx example
docs/coreprotect.md          Schema facts, business invariants, future design notes
AGENTS.md                    Invariants for future repository work
Dockerfile                   Non-root image with pinned Python/dependencies
docker-compose.yml           Two-container stack, version 3.7
docker-compose.dev.yml       Optional development source mount/server
docker-compose.host-gateway.yml  Optional Linux host mapping
requirements*.txt            Pinned runtime/development dependencies
```

## Production compatibility

Production uses **standalone `docker-compose` 1.25.0**, not Compose v2. Every command here
uses the legacy executable. All Compose files declare `version: "3.7"`; there are no
profiles, top-level name, develop keys, or modern depends_on conditions. Startup waits
for PostgreSQL in Python because this Compose format does not wait for database health.

The target is Ubuntu 20.04.4, kernel 5.4, Docker 24.0.2, overlay2, cgroup v1/cgroupfs,
host Nginx 1.18 and Certbot. Host Python 3.8 is not used. Container image versions are
pinned; update them deliberately. No Docker/containerd/Compose upgrades, daemon edits,
existing network changes, or Pterodactyl/Wings modifications are required.

Only web port `127.0.0.1:8086` is published. PostgreSQL has no published host port and
uses a project-owned network and named volume. The network allows outbound Discord traffic;
it is not an `internal: true` network. Keep a stable, unique project name. No globally
fixed container/network names are introduced. Existing services are untouched.

Logs rotate at 10 MB × 3 files per service. `.dockerignore` excludes secrets and build/test
artifacts. Static files are collected at startup. Web runs as UID 10001 without Linux
capabilities. Monitor the host's roughly 75 GB free disk and avoid global Docker pruning.

## Local development

Use a Docker host with standalone `docker-compose`. No host Python packages are required.
From the repository root:

```sh
cp .env.example .env
```

On PowerShell use `Copy-Item .env.example .env`. Edit `.env` before starting:

- Set a fresh random `DJANGO_SECRET_KEY` of at least 50 characters and a different strong
  `POSTGRES_PASSWORD`. On a machine with OpenSSL, `openssl rand -hex 32` generates one
  suitable secret. Never commit either value.
- Set `DJANGO_DEBUG=true`, `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1`, and
  `DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8086`.
- Set `DISCORD_REDIRECT_URI=http://localhost:8086/auth/callback/` and register that exact
  development callback in Discord. Use `localhost` consistently in the browser.
- Complete Discord configuration below. CoreProtect can remain blank initially.

Exact local startup command:

```sh
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Open `http://localhost:8086`. This override mounts source and runs Django's reloading
development server; production uses Gunicorn. Missing Discord configuration produces an
explanatory login screen, not an authentication bypass. Development disables HTTPS redirects
and Secure cookies for loopback HTTP. Never enable debug publicly. The app does not auto-load
`.env` when running Python outside Compose.

## Discord setup — manual

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
   Copy its application/client ID and OAuth client secret into `.env`.
2. Register exact redirects: **development** `http://localhost:8086/auth/callback/`;
   **production** `https://admin.spicy.is/auth/callback/`. A separate development application
   is useful for keeping environments independent.
3. Create its bot identity, store the bot token in `.env`, and install it in the spicy.is
   guild using a guild installation with the `bot` scope. No commands, gateway process,
   role-management, or Discord Administrator permission is needed. This is a REST credential
   for individual-member reads, not a running Discord bot feature.
4. Enable Discord Developer Mode and copy the numeric **guild ID**, **Admin role ID**, and
   **Minecraft Overlord role ID**. Set the matching variables. Patron's ID is optional and
   grants nothing yet. Role names never determine access.
5. Verify the bot belongs to the configured guild and can perform
   [Get Guild Member](https://docs.discord.com/developers/resources/guild#get-guild-member).
   This implementation does not list members and does not require enabling the privileged
   member-list intent. Validate the endpoint with the real application/guild during setup.
6. Give your own Discord account an allowed role. Restart web after changing environment
   values. No local account or `createsuperuser` is needed; OAuth creates your profile.

The [OAuth authorization-code flow](https://docs.discord.com/developers/topics/oauth2) uses
one-time session-bound state with a 10-minute lifetime. Login and logout use CSRF-protected
POSTs. Callback redirects always return to the dashboard. User tokens are never persisted.
Profile ID, username, display name, avatar hash, and last successful login are stored.
Sessions expire after 12 hours; role checks happen independently. API failures/rate limits
deny protected requests with a clear 503 until retry is allowed.

## Environment reference

Deployment values come from environment variables. `.env.example` contains placeholders
only. Compose reads `.env`; protect its file permissions on the host.

| Variable | Purpose / default |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Stable isolated project prefix; example `spicyadmin` |
| `WEB_PORT` | Loopback port, default `8086`; update Nginx/callbacks if changed |
| `DJANGO_SETTINGS_MODULE` | Compose fixes `config.settings.base`; tests explicitly select `config.settings.test` |
| `DJANGO_DEBUG` | Default false; true only for local development |
| `DJANGO_SECRET_KEY` | Required random secret, at least 50 characters |
| `DJANGO_ALLOWED_HOSTS` | Required comma-separated production hosts; example `admin.spicy.is`; no wildcard |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Exact comma-separated origins; example `https://admin.spicy.is` |
| `POSTGRES_DB` | Portal database, default `spicy_admin` |
| `POSTGRES_USER` | Portal database user, default `spicy_admin` |
| `POSTGRES_PASSWORD` | Required strong password for initial volume setup |
| `POSTGRES_HOST` | Default `postgres`; fixed by Compose |
| `POSTGRES_PORT` | Default `5432`; fixed by Compose, never published |
| `DISCORD_CLIENT_ID` | Required Discord application ID |
| `DISCORD_CLIENT_SECRET` | Required OAuth client secret |
| `DISCORD_BOT_TOKEN` | Required bot credential for current member-role reads |
| `DISCORD_GUILD_ID` | Required guild/server ID |
| `DISCORD_ADMIN_ROLE_ID` | Required role ID granting portal and diagnostics access |
| `DISCORD_OVERLORD_ROLE_ID` | Required Minecraft Overlord role ID granting normal portal access |
| `DISCORD_PATRON_ROLE_ID` | Optional; reserved, no Phase 1 access |
| `DISCORD_REDIRECT_URI` | Required exact registered callback; HTTPS in production |
| `DISCORD_ROLE_CACHE_SECONDS` | Default `45`; accepted range 30–60 seconds |
| `COREPROTECT_DB_HOST` | Default `host.docker.internal`; configurable verified host/bridge IP |
| `COREPROTECT_DB_PORT` | Default `3306` |
| `COREPROTECT_DB_NAME` | Existing external DB name; optional until connecting CoreProtect |
| `COREPROTECT_DB_USER` | Dedicated SELECT-only MariaDB account |
| `COREPROTECT_DB_PASSWORD` | Password for the read-only account |
| `COREPROTECT_TABLE_PREFIX` | Default `co_`; 1–40 letters, digits, underscores |
| `COREPROTECT_TIMEOUT_SECONDS` | Default `3`; range 1–10, connection/socket/statement timeout |

`INSTALL_DEV` is a Docker **build argument**, not a runtime setting; the development override
sets it true to include Ruff/coverage. `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, and
`PIP_NO_CACHE_DIR` are fixed container behavior settings in the Dockerfile.
Changing `.env` does not rotate a password inside an already initialized PostgreSQL volume;
update PostgreSQL and application credentials together deliberately.

## CoreProtect and host connectivity

Have the database administrator provision a SELECT-only account. Do not reuse Minecraft's
writer. The app never migrates or owns this DB. See [CoreProtect details](docs/coreprotect.md)
for schema facts, natural-mining rules, adapter behavior, and manual validation.

The base Compose file has no host-alias dependency. On Linux set `COREPROTECT_DB_HOST` to a
verified Docker host bridge address, **or** opt into Docker Engine's host-gateway mapping:

```sh
docker-compose -f docker-compose.yml -f docker-compose.host-gateway.yml config --quiet
docker-compose -f docker-compose.yml -f docker-compose.host-gateway.yml up -d --build
docker-compose -f docker-compose.yml -f docker-compose.host-gateway.yml exec web python -c "import socket; print(socket.gethostbyname('host.docker.internal'))"
```

Docker 24 supports the mapping, but its combination with the exact production Compose 1.25.0
installation needs verification. If rejected or unreachable, omit the optional file and use
the verified bridge IP. Do not upgrade Compose or change existing Docker networks to make
the alias work. Consistently use the same `-f` arguments for subsequent lifecycle commands.
Docker Desktop usually provides this hostname directly.

Sign in as Admin and open **Diagnostics** to check recorded version, dynamic worlds, and
material resolution without scanning `co_block`. If MariaDB is down, the dashboard shows
unavailable and documentation still works. MariaDB listener/firewall/routing and account-host
grants require manual verification. A host-loopback-only MariaDB listener is not bridge-accessible.

## Tests and quality checks

After creating `.env` and building the image, the exact offline test command is:

```sh
docker-compose run --rm --no-deps web python manage.py test --settings=config.settings.test
```

Tests use ephemeral SQLite and mocked external services. No running PostgreSQL, Discord,
CoreProtect, or live credentials are required. Coverage includes role hierarchy/revocation,
guild removal, API failures, OAuth state/replay/cancellation, CSRF/logout, password exclusion,
Markdown safety, read-only queries/timeouts/mappings, and diagnostics authorization.
SQLite tests do not validate PostgreSQL locking or real MariaDB transaction semantics.

Use the development image for linting and coverage:

```sh
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build web
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps web ruff check .
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps web ruff format --check .
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps web djlint templates --check
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps web coverage run --source=accounts,portal,documentation,coreprotect,analytics manage.py test --settings=config.settings.test
docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps web coverage report
docker-compose run --rm --no-deps web python manage.py makemigrations --check --dry-run --settings=config.settings.test
```

Optional Python 3.12+ workstation verification (not production setup): create `.venv`, install
`requirements-dev.txt`, then run `python manage.py test --settings=config.settings.test`,
`ruff check .`, and `ruff format --check .`. Test settings contain only dummy values.

## Production-style commands — manual

Set `DJANGO_DEBUG=false`, production hosts/origin/callback, and real secrets first.
Check the loopback port is unused. Exact startup command:

```sh
docker-compose up -d --build
```

Routine commands:

```sh
docker-compose config --quiet
docker-compose build
docker-compose up -d
docker-compose ps
docker-compose logs -f web
docker-compose exec web python manage.py check --deploy
docker-compose exec web python manage.py migrate --check
docker-compose exec web python manage.py clearsessions
docker-compose down
```

`config --quiet` avoids printing secrets. Startup waits for PostgreSQL, runs portal-only
migrations, collects static files, and starts two Gunicorn workers. Run `clearsessions`
periodically to remove expired sessions. Back up PostgreSQL before later schema upgrades.
`down` retains its volume; do not add `-v` unless deliberately deleting portal data.
No deployment is performed automatically by this repository.

## Host Nginx and Certbot — manual

Review [the example site](deploy/nginx/admin.spicy.is.conf.example). It supports host Nginx 1.18,
proxies to `127.0.0.1:8086`, overwrites forwarded headers, and suppresses OAuth callback query
logs. Gunicorn logs paths without query strings. WhiteNoise serves static assets from web;
no host static volume, Nginx container, or Certbot container is needed.

Manual order: configure DNS, obtain a certificate using the existing host Certbot workflow
(for example a reviewed temporary HTTP site and the Nginx plugin), replace the marked
certificate-path placeholders, review/install the final site, run `sudo nginx -t`, and
reload Nginx only after validation succeeds. Do not enable the TLS example before its
certificate paths exist. No host edits, certificate commands, or reloads run automatically.
Keep all existing sites and Pterodactyl services intact.

Django trusts `X-Forwarded-Proto` because host Nginx overwrites it and web binds to loopback.
Production enforces HTTPS, Secure/HttpOnly session cookies, SameSite=Lax, private no-store
responses, restrictive CSP, same-origin referrers (no-referrer on OAuth callbacks), and
clickjacking protection. HSTS applies only to
this hostname. Do not configure intermediaries to cache protected pages or log OAuth queries.

`check --deploy` intentionally reports `security.W005` and `security.W021`: HSTS subdomain
inclusion and browser preloading are not enabled without a reviewed host/TLS policy.
These two warnings are expected; other production security warnings need investigation.

## Verification boundary and next step

See [the Phase 1 verification record](docs/verification.md) for completed checks and limits.

Real Discord application permissions/callbacks, PostgreSQL multi-worker locking, actual
CoreProtect schema and grants, host routing, Docker startup under Compose 1.25.0, and Nginx/TLS
need validation on a suitable host. Static schema validation does not prove runtime compatibility.

Phase 2A is implemented; see [CoreProtect query and validation details](docs/coreprotect.md).
See the [Phase 2A verification record](docs/phase-2a-verification.md) for local check results
and the remaining production validation boundary.
Before using production counts broadly, validate UUID formats, known natural/placed events,
same-second rowid ordering, and the MariaDB execution plan on a narrow range. Phase 2C and
later work require a new scope request.

## Mining analytics (Phase 2B.1)

Open **Ore Statistics / Diamonds** at `/ore-statistics/diamonds/`. Access still requires
`minecraft.analytics`. **All time / All worlds remains the default and primary view.**
Natural diamond counts retain the strict historical player-placement exclusion in CoreProtect.
Stone/deepslate counts intentionally include previously placed blocks when their breaks qualify.

High-volume denominator scans exceeded production timeouts. Denominators now use compact
PostgreSQL daily aggregates, maintained by `sync_mining_analytics`. All Time never falls back
to a live full-history denominator scan, even before initialization. Exact partial-day ranges
combine complete PostgreSQL days with at most two CoreProtect windows shorter than 24 hours.
CoreProtect remains read-only; its schema, indexes, and timeouts are unchanged.

Two independently sorted tables show normal diamonds versus stone, and deepslate diamonds
versus deepslate. Each shows Player, target count, base count, targets per 1,000 base blocks,
and base blocks per target. Only natural miners in that layer appear. Zero divisors show a
dash; fewer than 1,000 corresponding base blocks receives a neutral Small sample label.

The combined UTC calendar and radial 24-hour clock retain their whole-day defaults,
inclusive-start/exclusive-end semantics, keyboard/touch controls, Cancel behavior, and
non-JavaScript fallback. Both tables have independent sticky headers and support both themes.

**This phase adds a portal PostgreSQL migration and requires an initial sync.** Until it
finishes, ratios are unavailable. Freshness is displayed, with a warning after 15 minutes
or a failed sync; data older than 24 hours becomes unavailable. Successful complete reports
retain their 45-second per-process cache, keyed additionally by sync generation.

Read [the rollup operations and validation guide](docs/mining-rollups.md) before production
use. It covers migration order, restart-safe backfill, incremental sync, recent rollback
reconciliation, manual rebuilds, and a recommended future five-minute cadence. No scheduler,
new dependencies, environment variables, infrastructure, or later ore features are added.
Historical checks remain in [Phase 2A verification](docs/phase-2a-verification.md) and
[Phase 2B verification](docs/phase-2b-verification.md).
Current checks and the repeatable browser harness are documented in
[Phase 2B.1 verification](docs/phase-2b1-verification.md).

## Ore overview and sortable reports (Phase 2B.2)

**Ore Statistics** and the dashboard mining action now open `/ore-statistics/`, with compact
Diamonds / Ancient Debris / Emerald cards and shared material navigation. Cards show natural
block totals and unique target miners across All Time; they do not query denominators.
Detail pages retain the UTC filters/calendar/clock and show Deepslate before Normal where
applicable. Ancient Debris uses Netherrack; Emerald uses Stone/Deepslate.

Every table sorts by ratio descending initially, always keeping small samples last.
Clickable keyboard-accessible headers sort any column. Each table independently persists
its Minimum sample in the browser: 250/500/1000/2500/5000/10000, with configurable code
defaults currently 1000. Changes only reclassify/reorder existing rows and never query data.

**Upgrade action:** Netherrack joins the existing rollup and changes its material signature.
Existing Phase 2B.1 installations require `sync_mining_analytics --full-rebuild` with the
updated image, then an ordinary sync to catch up. Detail ratios remain unavailable until
completion; overview cards still work. This phase needs no additional database migration.
No rebuild or deployment is run automatically by this change.

See [ore configuration, sorting, assets, and upgrade instructions](docs/ore-statistics.md)
and [Phase 2B.2 verification](docs/phase-2b2-verification.md). CoreProtect remains read-only;
All Time still makes no live denominator scan. No infrastructure or timeout changes apply.
