# Phase 2B.4 frontend polish and verification

Implemented on `phase-2b-mining-ratios`. No push, merge, deployment, infrastructure changes,
CoreProtect changes, migration, timeout increase or later-phase feature was introduced.

## Changes and causes

**Dropdowns:** The shared filter/sample CSS combined padded, custom-painted select controls
with the browser's native appearance. There was no shared hover/option-state rule; native
inner highlighting could differ from the full CSS control width. Selects now use one
centrally styled surface (`appearance: none`), an external SVG chevron, reserved arrow
padding, full border-box hover/focus backgrounds and visible keyboard outlines. Native
option hover/focus/selection uses system Highlight/HighlightText colors, and forced-colors
mode restores native appearance. No custom select library or replacement ARIA widget was
added. All time ranges, samples and audit actor/type/result/page-size controls share it.

Traditional select popups remain browser/OS-rendered; exact popup visuals need a final check
on production Firefox/OS. CSS cannot guarantee identical native popup internals across
platforms ([MDN native-select styling](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms/Advanced_form_styling)).
The full control surface and keyboard states pass Firefox and Edge browser checks.

**Scrollbars:** `#00fb9a` thumbs use a dark neutral track for contrast in both themes.
Hover lightens the accent. Firefox uses `scrollbar-color`/`scrollbar-width: auto`; WebKit
pseudo-elements specify a 12px scrollbar, rounded track/thumb and a 2px inset border.
Native Firefox controls determine corner rounding/width; overlay visibility follows browser
and OS preferences. No brittle arrow emulation was added.

**Fades:** the primary bottom cue is 44px, opacity 1, with a moderately stronger gradient,
visible whenever more vertical content remains. It disappears at bottom and returns when
scrolling upward. Top is independently 10px/0.65 opacity, absent at true zero and subtle
after scrolling; sticky text remains crisp. Left/right remain 14px/0.95 and track their
own boundaries. Top/bottom leave room for the scrollbar. No overflow means no edge fade.

**Initialization:** previously each table was wrapped and measured immediately, mixing
layout reads and class writes table by table; ResizeObserver/MutationObserver also called
that measurement directly. The shared implementation now waits for DOMContentLoaded and
the other deferred enhancements, schedules measurement with requestAnimationFrame, reads
all table geometries before writing any edge classes, and coalesces scroll/resize/content
notifications. Initial setup, window load/pageshow and font readiness request measurement
without any first-scroll dependency. The old shared 14px bottom/top rule also made the
primary bottom cue too weak. Chromium did initialize before scroll in earlier tests; the
new implementation explicitly covers the later styles/content readiness boundaries reported
from production Firefox rather than assuming the old first synchronous read was sufficient.

**CSP:** repository inspection found no authored inline script blocks, inline event handlers,
style tags or template style attributes. All scripts were already static same-origin files.
The radial clock did set `button.style.left/top`; these now use finite data-position
attributes with coordinates in `static/css/mining-clock.css`. Clock rendering assembles a
DocumentFragment before replacing labels. SVG hand coordinates remain SVG attributes.
No policy relaxation, nonce workaround, eval, unsafe-inline, wildcard source or CSP removal.

Direct CSSOM property assignment is normally permitted under style-src, unlike literal style
attributes ([MDN style-src](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/style-src)).
Thus we do not claim the old clock writes explain every reported inline-style warning, or
invent an inline-script source absent from this checkout. The complete normal-use Firefox
and Edge flows captured **zero securitypolicyviolation events**. If production still reports
violations, check its exact served asset version and the blocked source/line/directive in
Firefox; distinguish extension/devtools activity from application code.

The tiny synchronous external `theme.js` stays before styles to choose the stored theme
before painting. It only reads LocalStorage and writes a root data attribute; it performs
no geometry reads. Other scripts remain deferred. Clock pointer geometry is read only on
user interaction. No warning suppression or artificial initialization timeout was added.

## Validation

| Check | Result |
| --- | --- |
| `python manage.py test --settings=config.settings.test` | 229 tests passed |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `makemigrations --check --dry-run --settings=config.settings.test` | No changes detected |
| `djlint templates --check --lint` | 19 templates; no errors or formatting changes |
| `git diff --check` | Passed |
| Production WhiteNoise compressed-manifest static collection | 36 files post-processed in ignored local artifacts |
| `python scripts/check_browser.py` | Full Edge regression passed |
| `python scripts/check_browser.py --browser firefox` | Full Firefox 153 regression passed |

New browser coverage checks initial bottom visibility without any scroll, independent
top/bottom heights and opacity, disappearance/reappearance, dynamic row removal, native
select full-surface hover and keyboard focus in both themes, shared audit selects, scrollbar
colors and absence of inline styles after rendering the clock. Existing resize/horizontal
overflow/sticky, table sorting, independent sample persistence, audit/CSRF POST failure,
Admin permissions, calendar/radial clock and non-JS checks remain. CSP violations are captured
across navigations via a browser-context monitor and must remain empty.

Firefox uses pointer clicks for the coordinate-based clock test; Edge additionally performs
touchscreen taps. No Firefox mobile-touch equivalence is claimed. Explicit navigation waits
and computed CSS dimensions replace Chromium-specific timing/pixel rounding assumptions in
the harness. Playwright Firefox is an optional local test download under ignored
`.artifacts/playwright`, not a system browser installation or runtime dependency.

The harness uses a loopback server, mocked external APIs and disposable SQLite. Screenshots
of Firefox light-mode mining and the radial clock were inspected. Neither mocked API tests
nor headless runs establish production MariaDB/PostgreSQL behavior or every OS native popup
appearance. Visually confirm dropdown popups, thumb visibility and initial fades on the
production Firefox/browser settings and compare any remaining CSP/FOUC warning source.

## Discord session investigation

A concrete bug was reproduced before editing auth code: the second device's OAuth login
regenerated the user's unusable password, changing Django's session auth hash and making
the first device's next GET return 302. The narrow fix preserves an already-unusable
password. The same two-client test passes afterward; additional tests cover navigation,
role revocation/outage without session changes, profile edits, explicit credential resets
and a deliberate test SECRET_KEY change.

All session settings remain unchanged (30 days, save-every-request, Secure, SameSite Lax,
host-only `sessionid`, path `/`). OAuth state/key rotation and Discord revalidation are
preserved. See [the complete reviewed paths, ranked causes and next runtime checks](discord-session-investigation.md).
This demonstrates and fixes one matching mechanism, not proof that every past incident
had that cause. No speculative rewrite or persistent diagnostic logging was added.

## Proxy trust and retention

IP selection code is unchanged: only explicitly trusted socket peers can supply a single
validated XFF value. Documentation and `.env.example` identify the reported production
host/Docker bridge peer `172.26.0.1`, trusted because host Nginx overwrites forwarded IPs.
It is not a default or hardcoded trust entry. No historical IP rows are modified.

Retention remains 365 days. A daily prune run only removes events older than that cutoff,
maintaining a rolling 365-day history. No recent-row deletion, scheduler or migration.

## Files changed

- `static/css/portal.css`, new `static/css/mining-clock.css` and `static/img/select-chevron.svg`.
- `static/js/table-scroll.js`, `static/js/mining-clock.js`, `templates/base.html`.
- `accounts/views.py` and new `accounts/test_sessions.py` for the demonstrated session bug.
- `scripts/check_browser.py` and new `scripts/frontend_browser_checks.py`.
- `.env.example`, `README.md`, `AGENTS.md`, `docs/audit-log.md`, this verification record,
  and `docs/discord-session-investigation.md`.
