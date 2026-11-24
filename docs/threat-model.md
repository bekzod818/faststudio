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

| Control | Tests |
|---|---|
| Every route except `POST /auth/login` is on the session-protected router; a test enumerates all mounted API routes and asserts 401 without a session. | `tests/integration/security/test_auth.py::test_every_api_route_except_login_requires_a_session` |
| Session cookie signed with itsdangerous (HMAC), purpose-specific salt; tampered, truncated, forged-payload or foreign-key cookie ⇒ 401 and the cookie is cleared. | `tests/unit/auth/test_tokens.py`, `tests/integration/security/test_auth.py` |
| Absolute expiry via the signed issue time (`session_max_age`), plus a 60 s future-skew limit; expired ⇒ 401. | `tests/unit/auth/test_tokens.py`, `tests/integration/security/test_auth.py` |
| `auth_version` in cookie must match the user's current value (`ModelUserBackend`: SHA-256 of password hash + active/admin flags); password change, deactivation or losing admin rights invalidates sessions. `AuthenticatedUser.auth_version` is a required, non-empty field so custom backends cannot silently disable this. | `tests/integration/security/test_auth.py`, `tests/unit/auth/test_model_backend.py`, `tests/unit/test_authenticated_user.py` |
| `ModelUserBackend` admits only active **and** admin users; its column configuration is validated at startup. | `tests/unit/auth/test_model_backend.py` |
| Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path` = browser-visible admin root (proxy prefix + `base_url`), `Max-Age` = `session_max_age`. | `tests/integration/security/test_auth.py` |

### T2. Credential attacks and user enumeration

| Control | Tests |
|---|---|
| argon2id hashing (`argon2-cffi` defaults); verification never raises on malformed hashes; no plaintext ever stored or logged (failed logins log only the client address). `LoginRequest` hides the password from `repr` and validation errors; passwords are capped at 1024 chars (argon2 cost) and usernames reject control/bidi characters (log injection). | `tests/unit/auth/test_passwords.py`, `tests/unit/schemas/test_contract.py` |
| Identical status, body and code for unknown user vs wrong password vs inactive/non-admin. | `tests/integration/security/test_auth.py` |
| Dummy argon2 verification for unknown or ambiguous usernames and for rows without a usable argon2 hash (NULL, legacy bcrypt, SSO-only); inactive/non-admin rows still verify the password; the dummy hash is computed at startup; the `AuthBackend` protocol documents this as a requirement for custom backends. | `tests/unit/auth/test_model_backend.py` (asserts the verifications run) |
| Login rate limit (default 5 / 15 min per client IP + username normalized with NFKC/casefold/trim, counted before verifying, reset on success; rejected attempts do not extend the lockout) ⇒ 429 with `Retry-After`; pluggable `RateLimiter`. | `tests/unit/security/test_rate_limit.py`, `tests/integration/security/test_auth.py` |
| Constant-time comparisons (`hmac.compare_digest`) for CSRF tokens, CSRF header vs cookie, and `auth_version`. | code review, `tests/unit/auth/test_tokens.py` |

Residual risks (documented, accepted for v0.1):

- The in-memory limiter is per process; multi-worker deployments need a
  shared `RateLimiter`.
- Limits are per client IP + username. An attacker with many addresses (e.g.
  rotating IPv6) gets more guesses against one account, and database
  collations that treat spellings as equal beyond NFKC/casefold/trim (e.g.
  accent-insensitive) may give extra buckets. Use a shared limiter with a
  per-account or per-network budget for internet-facing admins.
- Anyone who knows an admin's username can keep that account locked out from
  their IP (5 attempts per window). Behind a reverse proxy without trusted
  proxy headers (uvicorn `--proxy-headers --forwarded-allow-ips`), all clients
  share one IP, so this affects everyone.
- The limiter keeps at most 10 000 keys (least recently used evicted), so
  spraying that many keys can reset a lockout.
- `ModelUserBackend` refuses logins when a username matches several rows (and
  warns at startup if the column is not declared unique), and does not rehash
  passwords with outdated argon2 parameters (it never writes to the host's
  user table).

### T3. Cross-site request forgery

| Control | Tests |
|---|---|
| All POST/PUT/PATCH/DELETE under `/api/` (including login, logout and unknown paths, checked before routing) require header `X-FastStudio-CSRF` equal to cookie `faststudio_csrftoken` (double submit) and an HMAC-valid token. | `tests/integration/security/test_auth.py`, `tests/integration/test_errors.py` |
| After login the token is bound to the session id (`HMAC(key, sid|nonce)`); a token from another session, or an anonymous token while signed in (cookie tossing), is rejected (login itself still accepts an anonymous token). | `tests/unit/auth/test_tokens.py`, `tests/integration/security/test_auth.py` |
| `Origin` / `Sec-Fetch-Site` must indicate same origin when present. Enforced for **every** `/api/*` request, including GET, so a permissive host CORS policy cannot expose admin reads (ADR-0008). | `tests/integration/security/test_origin.py`, `tests/integration/security/test_auth.py` |
| `SameSite=Lax` session cookie as defense in depth. | `tests/integration/security/test_auth.py` |
| Token rotated on login and logout, and reset to an anonymous token whenever an invalid session is cleared; a missing or invalid token cookie is replaced on the next response (never on cacheable `/assets/` responses). | `tests/integration/security/test_auth.py` |

### T4. Injection (SQL / query manipulation)

| Control | Tests |
|---|---|
| No SQL text is built from input; all queries are SQLAlchemy Core/ORM expressions with bound parameters, built only in `faststudio/query/`. | code review, bandit, `tests/integration/api/test_list_injection.py` |
| `ordering` fields must be in the sortable allowlist (`RegisteredModel.sortable_fields`: `list_display` + default `ordering`, minus `json`/`unsupported`, computed at `register()`); `filter[...]` fields in `list_filter`; values in declared choices; unknown or repeated parameters ⇒ 400 without echoing values. | `tests/unit/schemas/test_contract.py`, `tests/integration/api/test_list_injection.py`, `tests/unit/query/test_params.py` |
| Search uses `ILIKE` with bound parameters on `search_fields` only; `%`, `_` and `\` in input are escaped (`ESCAPE '\'`); `q` is limited to 200 characters without control characters. | `tests/integration/api/test_list.py`, `tests/unit/query/test_params.py` |
| Model identity and field names resolved via registry dicts, never `getattr` on user input; URL primary keys are parsed by column type (unparseable ⇒ 404). The allowlists are validated at `register()`. | `tests/unit/test_model_admin_validation.py`, `tests/integration/api/test_retrieve_and_choices.py` |
| `page_size` capped at `max_page_size`; `page` ≤ 100 000 (no unbounded offsets); `ordering` ≤ 5 fields. | `tests/integration/api/test_list_injection.py` |

### T5. Mass assignment and data exposure

| Control | Tests |
|---|---|
| Write bodies validated by generated Pydantic models (`extra="forbid"`, inputs hidden in errors); only writable fields exist on them. Readonly, excluded, managed and unknown fields ⇒ 422 and the row is unchanged. Primary keys are never writable on update; only natural keys (`create_only`) are accepted on create. Values are validated at least as strictly as the database (lengths, NUL, ranges, precision, enums, timezones, referenced rows); bodies are capped at 1 MiB. | `tests/integration/api/test_write.py`, `tests/unit/schemas/test_dynamic.py` |
| Writability is derived at `register()` and fails closed: database/SQLAlchemy-maintained columns (autoincrement, identity, computed, sequence, trigger defaults, `onupdate`, discriminator, version id), unsupported or value-converting types, and FKs whose own type is unsupported are `readonly`. Relations only point at primary keys. | `tests/unit/introspection/test_fields.py` |
| Defaults of `unsupported` or sensitive-looking fields are not published; other scalar defaults and column comments are (documented). | `tests/unit/introspection/test_fields.py` |
| `exclude`d fields never appear in metadata (checked on the whole serialized payload), list, retrieve or choices responses (relation labels use visible fields only, never `__str__`; lists load only displayed columns; label and choices queries go through the mapped entity so inheritance joins and discriminators apply), and cannot be configured as display, search, filter, ordering, readonly or label fields (which would turn search/sort into an oracle on hidden values, e.g. `password_hash`). Exclusion is column-based: another attribute mapped to an excluded column must be excluded too. Unknown `ModelAdmin` attributes fail registration, so a misspelled `exclude` cannot fail open. Visible fields with sensitive-looking names log a warning. | `tests/unit/test_model_admin_validation.py`, `tests/unit/schemas/test_contract.py`, `tests/integration/api/` |
| `can_create` / `can_edit` / `can_delete` enforced server-side (403, before reading the body), not only hidden in the UI. | `tests/integration/api/test_write.py` |
| Integrity errors return 409, data errors 422, other database errors 500, all with generic messages; FastStudio logs only the exception types (never SQL or parameters), also for unhandled database errors on reads. Error `details` are typed (`ValidationIssue`: `loc`, `msg`, `type` only) so a handler cannot echo submitted values. | `tests/unit/schemas/test_contract.py`, `tests/integration/api/test_write.py` |

### T6. Cross-site scripting

| Control | Tests |
|---|---|
| React renders all data as text; ESLint forbids `dangerouslySetInnerHTML` and `innerHTML`. | ESLint in CI |
| Runtime config is embedded as `<script type="application/json">` with `<`, `>`, `&` and non-ASCII escaped; the `<title>` is HTML-escaped; a title containing `</script>` cannot break out. Titles reject control/format characters. The pre-login config carries no version. | `tests/integration/test_spa.py`, `tests/unit/test_config.py` |
| Strict CSP: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`. No inline scripts. Applied by an ASGI wrapper *outside* the admin app, so redirects, 404/405/422 and 500 responses are covered too. | `tests/integration/security/test_headers.py`, `frontend/e2e/smoke.spec.ts` (fails on any CSP violation of the built SPA) |
| `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin`, restrictive `Permissions-Policy`, HSTS over HTTPS, `Cache-Control: no-store` except hashed assets. | `tests/integration/security/test_headers.py` |
| Static files: only `assets/` (Starlette `StaticFiles`, no symlinks) and top-level SPA files from an exact-name allowlist built at startup (no filesystem access per request: no case-folding aliases like `INDEX.HTML`, no NUL/long-name errors, no dotfiles or symlinks). Unknown `/api/*` never falls back to HTML. Only real asset paths (prefix match from the mount root) are cached as immutable. | `tests/integration/test_spa.py`, `tests/integration/security/test_headers.py` |
| Errors never leak internals: 500s return a generic body (details only in the `faststudio.api` log, path without query string); `HTTPException.detail` is never echoed; 422 details contain only `loc`/`msg`/`type` with `loc` parts capped at 64 chars and at most 50 issues (client-chosen key names can appear in `loc`, values never do). Admin 500s still propagate to host error handlers (ADR-0008). | `tests/integration/security/test_headers.py`, `tests/integration/test_errors.py` |
| Login `next` redirect accepts only in-app relative paths: no scheme-relative `//`, backslashes, control/bidi characters or percent-encoded control, C1 or bidi characters (checked after decoding), and never the login page itself in any case or trailing-slash form (no open redirect, no loop). A malformed CSRF cookie is treated as absent. | `frontend/src/lib/navigation.test.ts` |
| Frontend dependencies must not inject `<style>`/`<script>` elements or probe `eval` at runtime (CSP blocks and reports them): toasts are an in-house component, and zod runs with `jitless: true`. E2E records every `securitypolicyviolation` event, including blocked attempts a library swallows. | `frontend/src/components/ui/toaster.test.tsx`, `frontend/src/lib/zod-setup.test.ts`, `frontend/e2e/smoke.spec.ts` |

### T7. Secret management

| Control | Tests |
|---|---|
| No secret ships with the package or repo; gitleaks runs in pre-commit. | pre-commit |
| Missing, non-string, short (< 32 chars; < 43 if hand-written charset or word passphrase), placeholder, sequential/keyboard-run, low-diversity or whitespace-padded secret ⇒ `ConfigurationError` at startup; the value never appears in messages, exception chains or `repr`. False rejection of generated keys (token_urlsafe, token_hex, base64, Django-style) is negligible (< 1e-7 per key) and covered by a seeded regression test. | `tests/unit/security/test_secret.py`, `tests/unit/test_config.py` |
| Purpose-specific key derivation: sessions use itsdangerous with salt `faststudio.session` and HMAC-SHA256; CSRF tokens use an HMAC key derived with label `faststudio.csrf`. | `tests/unit/auth/test_tokens.py::test_session_and_csrf_keys_are_separate`, `::test_session_signature_uses_sha256` |

### T8. Supply chain

Dependabot, pip-audit, pnpm audit, CodeQL, SHA-pinned GitHub Actions, PyPI
Trusted Publishing (OIDC, no long-lived tokens), protected release
environments.

## Known limitations (v0.1.0)

- Stateless sessions cannot be revoked server-side before expiry, except by
  changing the user's password or deactivating them (ADR-0004).
- No granular permissions: every admin can access every registered model.
- No audit log.
- The foreign-key existence check on writes queries the referenced table even
  when its model is not registered, so an admin can learn whether a given key
  exists there (the database constraint would reveal the same via 409).
- Deletes are refused while an ORM relationship the delete would touch has
  related rows (one-to-many, many-to-many, or many-to-one with a `delete`
  cascade); hosts that rely on ORM cascades must remove related rows first
  (or use database-level `ON DELETE` rules). Rows inserted concurrently
  between that check and the delete can still be nulled or deleted by the
  ORM (a database foreign key alone does not stop the ORM's own `UPDATE ...
  SET fk = NULL`); only `passive_deletes=True` together with a database
  foreign key or `ON DELETE` rule leaves it to the database.
- Host-side logging of SQLAlchemy errors (e.g. `echo=True` or host exception
  handlers after ADR-0008 propagation) may include parameters; create the
  engine with `hide_parameters=True` in production.
- Read-API cost for authenticated admins: deep pages use `OFFSET` (up to
  page 100 000 × `max_page_size`), every list runs a `COUNT(*)`, contains
  search (`%q%`) always scans, and sorting on unindexed `list_display`
  columns is slow on large tables; text and JSON columns in `list_display` are
  returned whole. Index sortable/searchable columns and keep `list_display`
  lean for big tables.
- Secret strength checks are heuristics: a hand-chosen passphrase of 43+
  characters that avoids placeholder words and sequences can still pass. Documentation tells
  users to generate keys with `secrets.token_urlsafe(48)`.
- `AuthBackend` validation at startup checks shape (instance, async methods),
  not behaviour; a custom backend that leaks timing or returns users it should
  not is out of FastStudio's control.
