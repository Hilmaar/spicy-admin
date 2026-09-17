# Discord session investigation (Phase 2B.4)

## Demonstrated cause and narrow fix

The OAuth callback unconditionally called `user.set_unusable_password()` after every
profile refresh. Django's unusable password is a newly randomized string, not a constant.
`AbstractBaseUser.get_session_auth_hash()` incorporates that string. A successful login
on Chrome/phone therefore changed the hash expected by an existing Firefox session.
On its next authenticated request, Django rejected the old `_auth_user_hash`, flushed that
session, and the portal's permission decorator redirected the now-anonymous user to login.
An unexpired session row could exist until that request: row existence alone does not prove
the stored authentication hash is still valid.

`accounts/test_sessions.py` reproduces this using two independent Django clients and two
normal mocked Discord OAuth flows. Before the fix, the first client's next dashboard GET
returned **302 instead of 200** after the second client signed in. After the fix, both
clients remain authenticated and the first session key is unchanged.

The callback now calls `set_unusable_password()` **only if the user currently has a usable
password**. New users still receive an unusable password; local password authentication
remains disabled. Existing unusable password values survive ordinary profile refreshes.
Explicit credential resets still invalidate sessions; tests verify that protection.
There is no new session-hash scheme, authentication backend, migration, or bypass.

This fixes a demonstrated cross-device invalidation mechanism that matches the production
observations. It does not establish that every historical reauthentication had this cause.
Sessions already invalidated by older callbacks cannot be repaired by this change; affected
browsers may need one fresh login after a future authorized release.

## Paths reviewed

- `accounts/views.py`: login GET/POST, session-bound OAuth state, profile refresh, callback
  failures/success, and explicit logout; `accounts/discord.py`: OAuth URLs, HTTP/profile
  validation and membership failures; `accounts/models.py`: user manager, password/session
  inheritance and shared `GuildAuthorization`; `accounts/backends.py`: active-user restore.
- `accounts/permissions.py`: sole portal permission decorator, anonymous redirect, exact
  role-ID mapping, explicit user override, cache expiry, database locking and failure states.
- `portal/middleware.py`, context processors, all URL routing, view decorators and templates;
  frontend theme/navigation, analytics and audit scripts; auth-related audit hooks and service.
- `config/settings/base.py`/test settings, WSGI/startup, Gunicorn and Compose configuration;
  repository-wide session/auth/delete/redirect searches, existing auth/OAuth/override tests.
- Installed Django 5.2 session/auth implementation: `contrib/auth/base_user.py`, hashers,
  `contrib/auth/__init__.py`, session middleware, database session store and signing.

## Rotation, flushes and redirects

| Path | Session effect and conditions |
| --- | --- |
| Login GET | Renders sign-in page; does not clear or rotate an authenticated session |
| CSRF-protected login POST | `cycle_key()` preserves data while replacing the key; stores a fresh OAuth state |
| OAuth callback | Pops only pending state; rejects missing/expired/replayed/cancelled OAuth with 400 or 503, role/inactive denials with 403 |
| Successful callback | Django `login()` rotates an anonymous session; flushes a session belonging to a different user or carrying a mismatched auth hash; stores user/backend/hash and rotates the CSRF token |
| Explicit logout POST | Django `logout()` flushes that browser's session and redirects to `accounts:login` |
| Permission decorator | Redirects to `accounts:login` only when `request.user.is_authenticated` is false |
| Django session restore | Rejects absent/expired/unverifiable session data; inactive/missing user yields anonymous; mismatched session auth hash triggers flush |
| Error template | Offers a manual Return to sign in link; no automatic OAuth redirect |

No application code deletes Django session rows during normal navigation. The database
deletes in mining sync concern rollups; audit pruning only deletes old audit events.
No frontend handler flushes sessions or redirects after a failed audit request, CSP error,
CSRF failure, or role-check failure. There are no HTMX-specific authentication branches.

## Role cache, workers, cookies and restarts

Role revalidation is **authorization**, not a login timer. Expiry re-fetches membership
server-side using the bot; denied roles render 403, and API failures render 503 for ordinary
users. Neither response starts OAuth or removes `_auth_user_*` keys. Tests verify session
key/data survival through normal navigation, role revocation and membership API outages.
The explicit staff allowlist behavior remains unchanged.

`GuildAuthorization` is an independent one-to-one row referencing the user. Refreshing or
deleting it does not update the user's password or Django sessions. Permission refresh uses
database locks and shared PostgreSQL state, not worker-local login state. Audit inserts are
isolated and preserve authentication outcomes on failure.

Session settings remain: age **2592000 seconds (30 days)**, save every request, Secure in
production, SameSite Lax, name `sessionid`, host-only domain, path `/`. Django refreshes
expiry/cookie on eligible non-5xx responses; it does not rotate the key on ordinary saves.
A concurrent explicit logout/rotation can race another request; Django may return
`SessionInterrupted` instead of silently restoring the deleted session. No evidence ties
that race to the reported repeated reauthentication, so its behavior is unchanged.

Restarting workers alone does not discard PostgreSQL sessions. `SECRET_KEY` comes from
deployment environment, is required, and is never regenerated by application startup.
Changing it without fallbacks invalidates signatures/auth hashes; inconsistent secrets or
different databases across workers would also cause inconsistent session restoration.
No fallback-secret rotation is configured here. Tests demonstrate invalidation on an
explicit test secret change; there is no evidence production changed its secret.

The login POST's `cycle_key()` is correct fixation protection and preserves session data.
Multiple overlapping OAuth attempts in one browser can overwrite pending state and reject
an older callback, but that yields a login error, not an automatic recurring OAuth cycle.
Neither this rotation nor the 45-second role cache was changed.

## Ranked explanations and next runtime checks

1. **Proven code mechanism:** another device's OAuth callback regenerated the shared
   unusable password and invalidated existing session hashes. Fixed with the regression above.
2. **Possible, not observed:** changed/inconsistent `SECRET_KEY`, different database state
   across workers, or a missing/expired row. Compare deployment configuration privately and
   check whether failures align with releases/restarts; never publish secrets or session data.
3. **Possible, not observed:** browser cookie absent/overwritten/cleared, a same-host cookie
   collision, or an explicit logout/concurrent login flow. Inspect the affected browser's
   cookie attributes and the actual redirect/Set-Cookie chain at the next occurrence.
4. **Ruled out as an automatic trigger by code/tests:** ordinary role-cache expiry,
   `GuildAuthorization` refresh, read-only page navigation, threshold POST failures,
   CSP/CSRF errors and audit insertion failures.

If it recurs, inspect the **specific browser's** `sessionid` locally before completing
another OAuth flow. Privately compare it to its database row, expiry, presence of the three
auth keys, active user and configured backend, and whether the stored auth hash matches
the current user hash. Record only match/existence booleans, path/status, timestamps and a
short one-way fingerprint if correlating workers. Do not copy full cookies, session keys,
auth hashes, decoded session dictionaries, OAuth codes/tokens or secrets into logs/reports.
Compare the time with other devices' successful OAuth events and any manual sign-out.

No persistent diagnostic logger was added: the deterministic regression provides a narrower
fix, and production monitoring already exists. If failures remain after the release, a
temporary opt-in transition logger could capture authenticated-before/after, row-exists,
key-changed booleans and a short fingerprint; avoid raw values and remove it after diagnosis.
