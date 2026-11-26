# ADR-0004: Authentication, sessions and CSRF

- Status: Accepted
- Date: 2026-11-23
- Amended by: ADR-0011 (backend capabilities may manage users) and ADR-0013 (sessions), v0.2
- Implementation notes (M6): sessions are signed with HMAC-SHA256; see docs/threat-model.md T1-T3.
- Amended (v0.1.1): the logout limitation is spelled out in docs/threat-model.md
  (Known limitations) and pinned by `test_logout_does_not_revoke_a_copied_cookie`;
  v0.2 adds an idle timeout and "sign out everywhere", v0.3 a server-side store.

## Context

The admin needs secure login that fits existing applications without forcing
new tables or infrastructure, plus protection against CSRF.

## Decision

1. **Core owns sessions and CSRF.** `AuthBackend` only implements
   `authenticate()` and `get_user()`. Custom backends get cookies, expiry,
   CSRF and rate limiting for free.
2. **Built-in `ModelUserBackend` reads the host's own user model** with
   configurable columns (`username`, `password_hash`, `is_active`, `is_admin`).
   Only active admins can sign in. Hashes use argon2id; `hash_password()` is
   exported for seeding.
3. **Stateless signed session cookie** `faststudio_session` containing
   `{uid, av, sid, iat}`, signed with itsdangerous using a purpose-specific
   salt, `HttpOnly; Secure; SameSite=Lax; Path={base_url}`, absolute expiry
   `session_max_age` (default 8 h). `av` (auth_version) is derived from the
   user's password hash, so a password change invalidates all sessions.
4. **CSRF**: double-submit cookie `faststudio_csrftoken` + header
   `X-FastStudio-CSRF`, signed; bound to `sid` after login; rotated on login
   and logout; plus `Origin`/`Sec-Fetch-Site` same-origin check. Applies to
   every unsafe method including login.
5. **Rate limiting**: pluggable `RateLimiter`, default in-memory 5 attempts /
   15 min per client IP + username.

## Alternatives considered

- Server-side session store: true revocation but requires storage; in-memory
  default breaks with multiple workers. Deferred to ROADMAP v0.3.
- FastStudio-owned users table: easier onboarding but we would own a schema
  and migrations forever.
- JWT in `Authorization` header: needs JS-accessible token storage (XSS risk).

## Consequences

- No DB or Redis required for sessions.
- Logout cannot revoke a stolen cookie before expiry; mitigated by HttpOnly,
  short lifetime and `auth_version`. Documented in the threat model.

**Amendment (v0.2, ADR-0013).** The cookie gains a fifth item, the
last-seen time, only when `session_idle_timeout` is set; without it the
cookie stays the 4-item format above, and 4-item cookies are always
accepted. "Sign out everywhere" revokes every session of an account
without server-side state, through a random per-account token that is part
of `auth_version`. A stolen cookie in active use is still valid until
`session_max_age` unless the user signs out everywhere.
