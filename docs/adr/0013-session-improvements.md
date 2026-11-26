# ADR-0013: Idle timeout and "sign out everywhere" (still stateless)

- Status: Accepted (2026-11-25, maintainer approval with amendments A1–A7)
- Date: 2026-11-24
- Refines: ADR-0004. Plan: docs/plans/v0.2.md

## Context

Sessions are stateless signed cookies with an absolute lifetime; logout
cannot revoke a copied cookie (threat model, v0.1.1). A server-side store is
planned for v0.3. v0.2 should narrow the gap without adding storage.

## Decision

1. **The cookie payload gains `last_seen`** (`[uid, av, sid, iat, seen]`)
   **only when `session_idle_timeout` is set.** Otherwise the cookie keeps
   the 4-item v0.1 format, so rolling deploys and downgrades keep sessions.
   4-item cookies are always accepted, with `seen = iat`.
2. **`Admin(session_idle_timeout: timedelta | None = None)`.**
   - When it is set, a session whose `now - seen` exceeds it gets a 401.
   - **Sliding refresh:** the cookie is re-issued with a new `seen` only when
     `now - seen ≥ refresh_after`, where `refresh_after = min(timeout / 4,
     5 minutes)`. It is not re-issued on every request.
   - It is never re-issued on a 401 response.
   - `sid` is kept, so the CSRF binding survives.
   - The SPA does no background polling, which would defeat the timeout.
   - `iat` never changes, so `session_max_age` stays absolute.
   - Requires `session_idle_timeout ≤ session_max_age`.
3. **"Sign out everywhere"**: `POST /auth/sign-out-everywhere`, plus a UI
   button. The backend's `session_revocation` capability replaces a per-user
   **random** session token that is part of `auth_version`, so every existing
   cookie of that user fails on its next request. A random token means a
   database restore can't revive old cookies the way decrementing a counter
   could.
   - `contrib.auth` has a `session_token` column.
   - `ModelUserBackend` supports it only through the optional parameter
     `session_token_field="..."`, which names a string column of at least 43
     characters **in the host's own user model**. FastStudio never requires
     or creates that column.
     - When unset, the feature is disabled: the button is hidden
       (`capabilities.sign_out_everywhere` is false), the endpoint answers
       404, and `auth_version` keeps its v0.1 formula.
     - When set, the column is validated at startup.
     - Both cases are tested and documented.
   - Without the capability, the button is hidden
     (`MetaResponse.capabilities`).
4. **Password change.** `POST /auth/password` requires the current password.
   - A wrong value counts against the login rate limiters (per client and
     username, and per client), runs a dummy verify for constant timing, and
     returns a generic `422`, so a stolen session is not a password oracle.
   - On success it revokes other sessions (the hash is in `auth_version`)
     and re-issues the current session's cookie.
   - The admin set-password endpoint (ADR-0011) refuses the signed-in
     user's own account, so it cannot bypass this check.
   - For `ModelUserBackend`, both password endpoints are opt-in
     (`password_endpoints=True`).

## Alternatives considered

- **A server-side store now:** needs storage and a multi-worker design; it
  stays in v0.3.
- **Refreshing the cookie on every request:** every response would carry a
  `Set-Cookie`, and stolen cookies would be extended indefinitely.

## Consequences

- An idle stolen cookie expires sooner, and users can revoke all sessions.
  Neither works for a cookie that is in active use without the user's own
  action.
- With the idle timeout enabled, v0.1 workers reject the 5-item cookie, so
  enable it only after every worker runs 0.2. This is documented.

## Implementation notes (M20, 2026-11-26, maintainer-approved)

- `session_idle_timeout` and `session_max_age` both accept int seconds or a
  `timedelta` (bool refused; at least 60 seconds, as `session_max_age`
  already required in 0.1).
- `load()` also refuses a 5-item cookie whose `seen` is before `iat` or
  beyond the 60 s skew limit.
- The refresh is appended by a pure ASGI layer inside the security-headers
  layer, so it is `Cache-Control: no-store`; it is skipped on a 401 and on
  any response that sets the session cookie itself (login, logout, password
  changes, sign out everywhere). `Max-Age` is the remaining absolute
  lifetime.
- `ModelUserBackend(session_token_field=...)`: the column must be a string
  column of its own (not the key, username, password or a flag) of at least
  43 characters or unbounded; it is a secret field. NULL or empty values
  count as "" and still sign in; `create_admin` sets a fresh token; password
  changes leave it alone.
- When a write meets a 401 the SPA keeps the form in memory, asks for the
  password in a dialog and retries; a different account discards the form.
- Tests control time only by passing `clock=` to `SessionManager` from test
  code; the package has no time-shifting hook (a test checks this).
- An unsafe request with a session cookie that no longer loads (expired,
  idle) is `401 not_authenticated` before the CSRF check (previously `403
  csrf_failed`, since its token was bound to the dead session). This is what
  lets the UI offer the in-place sign-in; nothing runs in either case.
