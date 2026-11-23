# Threat model

FastStudio exposes read/write access to application data, so a compromise of
the admin is usually a compromise of the application. This document lists the
assets, attackers, threats and the controls FastStudio implements. **Every
control listed here must have a test that proves it**; the test locations are
listed per control and are checked by the `security-checklist` skill.

## Assets

- Application data reachable through registered models.
- Admin credentials (password hashes in the host's user table).
- Session cookies and CSRF tokens.
- `FASTSTUDIO_SECRET_KEY`.

## Attackers

| Attacker | Capability |
|---|---|
| Anonymous internet user | Sends arbitrary HTTP requests to the admin. |
| Malicious website | Makes the admin's browser send cross-site requests. |
| Low-privilege app user | Has an account in the host user table but is not an admin. |
| Admin with stolen session | Holds a valid cookie (XSS elsewhere, shared device). |
| Malicious data author | Stores crafted strings in data the admin later views. |

## Trust boundaries

Browser ⇄ admin API (untrusted input); admin API ⇄ database (only parameterized
SQLAlchemy expressions); host app configuration (trusted, validated at startup).

## Threats and controls

### T1. Authentication bypass

| Control | Tests (planned path) |
|---|---|
| Every route except `POST /auth/login` depends on the session dependency; a test enumerates all mounted routes and asserts 401 without a cookie. | `tests/integration/security/test_auth_required.py` |
| Session cookie signed with itsdangerous (HMAC-SHA), purpose-specific salt; tampered cookie ⇒ 401. | `test_session.py` |
| Absolute expiry via signed timestamp (`session_max_age`); expired ⇒ 401. | `test_session.py` |
| `auth_version` in cookie must match the user's current value (derived from the password hash); password change or deactivation invalidates sessions. `AuthenticatedUser.auth_version` is a required, non-empty field so custom backends cannot silently disable this. | `test_session.py`, `tests/unit/test_authenticated_user.py` |
| `ModelUserBackend` admits only active **and** admin users. | `test_model_backend.py` |
| Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path={base_url}`. | `test_session.py` |

### T2. Credential attacks and user enumeration

| Control | Tests |
|---|---|
| argon2id hashing (`argon2-cffi` defaults); no plaintext ever stored or logged. `LoginRequest` hides the password from `repr` and validation errors; passwords are capped at 1024 chars (argon2 cost) and usernames reject control/bidi characters (log injection). | `test_passwords.py`, `tests/unit/schemas/test_contract.py` |
| Identical status, body and code for unknown user vs wrong password vs inactive/non-admin. | `test_login.py` |
| Dummy argon2 verification for unknown users to equalize timing; the `AuthBackend` protocol documents this as a requirement for custom backends. | `test_login.py` (asserts verify called) |
| Login rate limit (default 5 / 15 min per client IP + username) ⇒ 429 with `Retry-After`; pluggable `RateLimiter`. | `test_rate_limit.py` |
| Constant-time comparisons (`hmac.compare_digest`) for all token comparisons. | code review + `test_csrf.py` |

Residual risk: the in-memory limiter is per process; multi-worker deployments
need a shared limiter. Rate limiting by IP behind a proxy requires the host to
configure trusted proxy headers correctly.

### T3. Cross-site request forgery

| Control | Tests |
|---|---|
| All POST/PUT/PATCH/DELETE (including login and logout) require header `X-FastStudio-CSRF` equal to cookie `faststudio_csrftoken` (double submit), signature-verified. | `test_csrf.py` |
| After login the token is bound to the session id (`HMAC(sid, nonce)`); a token from another session is rejected. | `test_csrf.py` |
| `Origin` / `Sec-Fetch-Site` must indicate same origin when present. Enforced for **every** `/api/*` request, including GET, so a permissive host CORS policy cannot expose admin reads (ADR-0008). | `tests/integration/security/test_origin.py`, `test_csrf.py` |
| `SameSite=Lax` session cookie as defense in depth. | `test_session.py` |
| Token rotated on login and logout. | `test_csrf.py` |

### T4. Injection (SQL / query manipulation)

| Control | Tests |
|---|---|
| No SQL text is built from input; all queries are SQLAlchemy Core/ORM expressions with bound parameters. | code review, bandit |
| `ordering` fields must be in the sortable allowlist (`RegisteredModel.sortable_fields`: `list_display` + default `ordering`, minus `json`/`unsupported`, computed at `register()`); `filter[...]` fields in `list_filter`; values in declared choices. Unknown ⇒ 400. | `tests/unit/schemas/test_contract.py`, `test_list_injection.py` |
| Search uses `ILIKE` with bound parameters on `search_fields` only; `%`/`_` in input are escaped. | `test_list_injection.py` |
| Model identity and field names resolved via registry dicts, never `getattr` on user input. The allowlists are validated at `register()` (unknown names, non-text search fields and non-boolean/enum filters fail startup). | `tests/unit/test_model_admin_validation.py`, `test_list_injection.py` |
| `page_size` capped at `max_page_size`; `page` bounded. | `test_pagination.py` |

### T5. Mass assignment and data exposure

| Control | Tests |
|---|---|
| Write bodies validated by generated Pydantic models with `extra="forbid"`; only writable fields exist on them. Readonly, excluded and unknown fields ⇒ 422 and the row is unchanged. Primary keys are never writable on update; only natural keys (`create_only`) are accepted on create. | `test_mass_assignment.py` |
| Writability is derived at `register()` and fails closed: database/SQLAlchemy-maintained columns (autoincrement, identity, computed, sequence, trigger defaults, `onupdate`, discriminator, version id), unsupported or value-converting types, and FKs whose own type is unsupported are `readonly`. Relations only point at primary keys. | `tests/unit/introspection/test_fields.py` |
| Defaults of `unsupported` or sensitive-looking fields are not published; other scalar defaults and column comments are (documented). | `tests/unit/introspection/test_fields.py` |
| `exclude`d fields never appear in metadata (checked on the whole serialized payload), list, retrieve or choices responses, and cannot be configured as display, search, filter, ordering, readonly or label fields (which would turn search/sort into an oracle on hidden values, e.g. `password_hash`). Exclusion is column-based: another attribute mapped to an excluded column must be excluded too. Unknown `ModelAdmin` attributes fail registration, so a misspelled `exclude` cannot fail open. Visible fields with sensitive-looking names log a warning. | `tests/unit/test_model_admin_validation.py`, `tests/unit/schemas/test_contract.py`, `test_exclude.py` |
| `can_create` / `can_edit` / `can_delete` enforced server-side (403), not only hidden in the UI. | `test_permissions.py` |
| Integrity errors return 409 with a generic message; SQL/driver text is only logged. Error `details` are typed (`ValidationIssue`: `loc`, `msg`, `type` only) so a handler cannot echo submitted values. | `tests/unit/schemas/test_contract.py`, `test_errors.py` |

### T6. Cross-site scripting

| Control | Tests |
|---|---|
| React renders all data as text; ESLint forbids `dangerouslySetInnerHTML` and `innerHTML`. | ESLint in CI |
| Runtime config is embedded as `<script type="application/json">` with `<`, `>`, `&` and non-ASCII escaped; the `<title>` is HTML-escaped; a title containing `</script>` cannot break out. Titles reject control/format characters. The pre-login config carries no version. | `tests/integration/test_spa.py`, `tests/unit/test_config.py` |
| Strict CSP: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`. No inline scripts. Applied by an ASGI wrapper *outside* the admin app, so redirects, 404/405/422 and 500 responses are covered too. | `tests/integration/security/test_headers.py`, `frontend/e2e/smoke.spec.ts` (fails on any CSP violation of the built SPA) |
| `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin`, restrictive `Permissions-Policy`, HSTS over HTTPS, `Cache-Control: no-store` except hashed assets. | `tests/integration/security/test_headers.py` |
| Static files: only `assets/` (Starlette `StaticFiles`, no symlinks) and top-level SPA files from an exact-name allowlist built at startup (no filesystem access per request: no case-folding aliases like `INDEX.HTML`, no NUL/long-name errors, no dotfiles or symlinks). Unknown `/api/*` never falls back to HTML. Only real asset paths (prefix match from the mount root) are cached as immutable. | `tests/integration/test_spa.py`, `tests/integration/security/test_headers.py` |
| Errors never leak internals: 500s return a generic body (details only in the `faststudio.api` log, path without query string); `HTTPException.detail` is never echoed; 422 details contain only `loc`/`msg`/`type` with `loc` parts capped at 64 chars and at most 50 issues (client-chosen key names can appear in `loc`, values never do). Admin 500s still propagate to host error handlers (ADR-0008). | `tests/integration/security/test_headers.py`, `tests/integration/test_errors.py` |
| Login `next` redirect accepts only in-app relative paths (no open redirect). | Vitest |

### T7. Secret management

| Control | Tests |
|---|---|
| No secret ships with the package or repo; gitleaks runs in pre-commit. | pre-commit |
| Missing, non-string, short (< 32 chars; < 43 if hand-written charset or word passphrase), placeholder, sequential/keyboard-run, low-diversity or whitespace-padded secret ⇒ `ConfigurationError` at startup; the value never appears in messages, exception chains or `repr`. False rejection of generated keys (token_urlsafe, token_hex, base64, Django-style) is negligible (< 1e-7 per key) and covered by a seeded regression test. | `tests/unit/security/test_secret.py`, `tests/unit/test_config.py` |
| Purpose-specific key derivation (separate salts for session and CSRF). | `test_session.py` |

### T8. Supply chain

Dependabot, pip-audit, pnpm audit, CodeQL, SHA-pinned GitHub Actions, PyPI
Trusted Publishing (OIDC, no long-lived tokens), protected release
environments.

## Known limitations (v0.1.0)

- Stateless sessions cannot be revoked server-side before expiry, except by
  changing the user's password or deactivating them (ADR-0004).
- No granular permissions: every admin can access every registered model.
- No audit log.
- Secret strength checks are heuristics: a hand-chosen passphrase of 43+
  characters that avoids placeholder words and sequences can still pass. Documentation tells
  users to generate keys with `secrets.token_urlsafe(48)`.
- `AuthBackend` validation at startup checks shape (instance, async methods),
  not behaviour; a custom backend that leaks timing or returns users it should
  not is out of FastStudio's control.
