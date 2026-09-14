# spicy-admin

Private staff portal for **spicy.is**, intended for `https://admin.spicy.is`.
Phase 1 includes Discord login, current-role authorization, a responsive dark/light dashboard,
documentation placeholders, and read-only CoreProtect diagnostics. Phase 2A adds natural
diamond mining counts with time/world filters. Other ores, denominator ratios, live activity,
player investigations, punishments, and integrations remain future scope.

## Architecture

```text
Browser → host Nginx / HTTPS → 127.0.0.1:8086 → web (Django + Gunicorn)
                                                  ├─ postgres (portal state only)
                                                  ├─ Discord HTTPS API (identity + roles)
                                                  └─ host MariaDB (CoreProtect, SELECT-only)
```

- Python 3.12, Django 5.2 LTS, server-rendered templates, small vanilla JavaScript,
  handwritten CSS, and WhiteNoise static delivery. No frontend build or API tier is needed.
  Django 5.2 is an [LTS release](https://www.djangoproject.com/weblog/2025/apr/02/django-52-released/).
- PostgreSQL 16 stores users, sessions, and shared authorization state. Role results expire
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
same-second rowid ordering, and the MariaDB execution plan on a narrow range. Phase 2B and
later work require a new scope request.

## Diamond Mining Statistics (Phase 2A)

Open **Ore Statistics → Diamonds** at `/ore-statistics/diamonds/`. Admin and Minecraft
Overlord roles receive `minecraft.analytics` through the existing permission service.
The page shows Player / Diamond Ore / Deepslate Diamond Ore / Total, ordered by descending
total with deterministic name/UUID ties. It does not assign suspicion or cheating scores.

Default filters are **All time / All worlds**. Quick ranges are 24 hours, 7 days, and 30 days.
Custom ranges require both bounds in UTC (start inclusive, end exclusive). Choose Custom
range when filling the date fields. Date-only query values mean midnight; explicit offsets
normalize to UTC. All filters apply to candidate breaks; older player placements at the
same location/material still exclude a break. Same-second events order by rowid.

Results and dynamic world choices are cached for **45 seconds per Gunicorn process** using
LocMem. The page displays the exact bounds and timestamp of its cached query. CoreProtect
failures produce a distinct unavailable state; valid empty reports are labelled separately.
Authorization is always checked before cache access. No new environment variables, database
migrations, dependencies, services, or infrastructure changes are needed for Phase 2A.

The regular test command includes direct SQL semantic tests against synthetic SQLite
fixtures; no real CoreProtect connection is required. This does not verify MariaDB query
plans or runtime performance. Denominator counts/ratios, other ores, background aggregation,
and PostgreSQL copies of CoreProtect events remain deliberately deferred.
