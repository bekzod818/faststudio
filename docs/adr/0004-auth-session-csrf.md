# ADR-0004: Authentication, sessions and CSRF

- Status: Accepted
- Date: 2026-11-23
- Implementation notes (M6): sessions are signed with HMAC-SHA256; see docs/threat-model.md T1-T3.

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
