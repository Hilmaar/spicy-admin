# Phase 1 verification

Verified in the local Windows workspace on 2026-09-14. No push, merge, deployment,
production credentials, or changes to existing infrastructure were performed.

## Passed

- **53 automated tests**, with external Discord and CoreProtect access mocked.
- **99% statement coverage** across accounts, portal, documentation, and CoreProtect;
  tests and migrations excluded. This does not measure real integration correctness.
- Ruff lint and Python formatting checks; Django template formatting check.
- Django migration consistency: no ungenerated changes.
- Production static collection with manifest/compressed assets.
- Python dependency consistency (`pip check`).
- All three Compose files validated against the
  [official Compose 1.25.0 version 3.7 schema](https://github.com/docker/compose/blob/1.25.0/compose/config/config_schema_v3.7.json).
  Structural checks confirmed two services, loopback-only web publishing, and no PostgreSQL
  published ports.
- Headless Edge browser checks at 1440px desktop and 390px mobile: default dark mode,
  light-theme persistence after reload, responsive overflow, menu open/Escape-close,
  Markdown table display, unavailable diagnostics, and CSRF-protected logout.
  No JavaScript errors were reported. Preview identity and Discord avatar were test fixtures.
- `.env`, `.venv`, static build output, and local verification artifacts are ignored.

The local Python runtime was 3.12.9; the Dockerfile pins Python 3.12.14. Automated tests
used ephemeral SQLite. Browser verification used a separate ignored local SQLite database
and a loopback WSGI server, stopped when verification finished.

## Expected production security warnings

Django's production settings check reports only `security.W005` and `security.W021`.
HSTS subdomain inclusion and browser preload are deliberately disabled pending an explicit
host/TLS policy decision. HTTPS redirects, Secure cookies, HSTS for this hostname, host
validation, proxy awareness, CSP, CSRF, and frame protection are configured.

## Not verified here

Docker and standalone Compose are unavailable in this workspace. Container image build,
PostgreSQL startup/migrations and cross-worker locking, actual Compose 1.25.0 behavior,
and Linux host-gateway routing have not been exercised. Schema validation alone cannot
establish runtime compatibility.

Live Discord redirects/bot member reads, the production CoreProtect schema and SELECT-only
grants, MariaDB transaction/timeouts on the real server, host network/firewall/bind addresses,
and Nginx/Certbot TLS require manual integration validation. See the README for setup.
No Phase 2 analytics or integrations have been implemented.
