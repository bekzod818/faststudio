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
| Absolute expiry via the signed issue time (`session_max_age`), plus a 60 s future-skew limit; expired ⇒ 401. Logout clears the browser's cookie but cannot revoke a copy of it before expiry (see Known limitations). | `tests/unit/auth/test_tokens.py`, `tests/integration/security/test_auth.py` (incl. `test_logout_does_not_revoke_a_copied_cookie`) |
| `auth_version` in cookie must match the user's current value (`ModelUserBackend`: SHA-256 of password hash + active/admin flags); password change, deactivation or losing admin rights invalidates sessions. `AuthenticatedUser.auth_version` is a required, non-empty field so custom backends cannot silently disable this. | `tests/integration/security/test_auth.py`, `tests/unit/auth/test_model_backend.py`, `tests/unit/test_authenticated_user.py` |
| `ModelUserBackend` admits only active **and** admin users; its column configuration is validated at startup. | `tests/unit/auth/test_model_backend.py` |
| Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path` = browser-visible admin root (proxy prefix + `base_url`), `Max-Age` = `session_max_age` (on a sliding refresh: the remaining absolute lifetime). | `tests/integration/security/test_auth.py`, `tests/integration/security/test_session_idle.py` |
| Optional idle timeout (`session_idle_timeout`, ADR-0013): the cookie then carries a signed last-seen time; `now - seen > timeout` ⇒ 401, and a `seen` before the issue time or beyond the skew limit is refused. Active sessions slide at most every `min(timeout / 4, 5 min)`, keeping the session id (CSRF binding) and the issue time (absolute expiry unchanged). A refresh is never added to a 401 or to a response that sets the session cookie itself (login, logout, password changes, sign out everywhere). Responses carrying it are `Cache-Control: no-store` like every admin response. The SPA does not poll, so only real use slides a session. Off, the cookie is byte-identical to 0.1.x. Because any response may renew the cookie, the SPA cancels its query retries, aborts and awaits every request in flight, and sends nothing else until the logout, sign out everywhere or password change has settled, so a late refresh cannot bring a signed-out session back (a request from another open tab still can: use "sign out everywhere" on shared computers). **The idle timeout bounds abandoned cookies only; an attacker actively using a stolen cookie keeps it alive until the absolute `session_max_age` or "sign out everywhere".** | `tests/unit/auth/test_session_idle.py`, `tests/integration/security/test_session_idle.py`, `frontend/src/app/query.test.ts`, `frontend/src/app/App.test.tsx`, `frontend/src/api/client.test.ts` |
| "Sign out everywhere" (`POST /auth/sign-out-everywhere`, `session_revocation` capability): rotates a random per-account token that is part of `auth_version`, so every session of the account ends; needs a session and CSRF; clears this browser's cookie like logout. `contrib.auth` provides it; `ModelUserBackend` only with `session_token_field` (validated string column ≥ 43 characters, a secret field). `404` without the capability. | `tests/integration/security/test_sign_out_everywhere.py`, `tests/integration/contrib/test_contrib_auth.py` |
| The shipped package contains no hook that shifts session time or bypasses checks (no environment variable, flag or route); tests inject a clock through `SessionManager(clock=...)` from outside the package. | `tests/unit/test_no_test_hooks.py` |

### T2. Credential attacks and user enumeration

| Control | Tests |
|---|---|
| argon2id hashing (`argon2-cffi` defaults); verification never raises on malformed hashes; no plaintext ever stored or logged (failed logins log only the client address). `LoginRequest` hides the password from `repr` and validation errors; passwords are capped at 1024 chars (argon2 cost) and usernames reject control/bidi characters (log injection). | `tests/unit/auth/test_passwords.py`, `tests/unit/schemas/test_contract.py` |
| Identical status, body and code for unknown user vs wrong password vs inactive/non-admin. | `tests/integration/security/test_auth.py` |
| Dummy argon2 verification for unknown or ambiguous usernames and for rows without a usable argon2 hash (NULL, legacy bcrypt, SSO-only); inactive/non-admin rows still verify the password; the dummy hash is computed at startup; the `AuthBackend` protocol documents this as a requirement for custom backends. | `tests/unit/auth/test_model_backend.py` (asserts the verifications run) |
| Login rate limit (default 5 / 15 min per client IP + username normalized with accents removed, NFKC, casefold and trim, counted before verifying, reset on success; rejected attempts do not extend the lockout) ⇒ 429 with `Retry-After`; pluggable `RateLimiter`. | `tests/unit/security/test_rate_limit.py`, `tests/integration/security/test_auth.py` |
| Per-client budget across all usernames: at most 30 login attempts per client IP per 15 min (in-process, never reset by a success), so one address cannot spray a password over many usernames. | `tests/integration/security/test_auth.py::test_one_client_cannot_spray_many_usernames` |
| argon2 runs in worker threads (at most 4 concurrent verifications per event loop, the rest queue), so login floods cannot block the event loop the admin shares with the host app. Custom `AuthBackend`s must not hash on the event loop either. | `tests/unit/auth/test_passwords.py::test_async_verification_runs_off_the_event_loop` |
| Constant-time comparisons (`hmac.compare_digest`) for CSRF tokens, CSRF header vs cookie, and `auth_version`. | code review, `tests/unit/auth/test_tokens.py` |
| Password endpoints (opt-in for `ModelUserBackend`): changing one's own password needs the current one, verified in constant time (dummy verify for missing or unusable hashes); every attempt counts against both login limiters (429); success changes `auth_version` (signs out every other session) and re-issues the session and a CSRF token bound to it. Successful changes count against the per-client budget too (as logins do). Setting another account's password needs every permission and the model's edit hooks (checked before the lookup; object-level edit and view hooks apply, a hidden record is a 404), never targets one's own account, and signs that account out everywhere. New passwords pass the hard limits and the backend's validators (length, similarity to name and email, numeric-only, and a bundled list of 20 000 common passwords). Bodies are strict and never echoed; passwords are never logged. | `tests/integration/security/test_passwords.py`, `tests/unit/auth/test_validators.py` |

Residual risks (documented, accepted for v0.1):

- The in-memory limiter is per process; multi-worker deployments need a
  shared `RateLimiter`.
- Limits are per client IP + username and per client IP. An attacker with
  many addresses (e.g. rotating IPv6) gets more guesses against one account, and database
  collations that treat spellings as equal beyond NFKC/casefold/trim (e.g.
  accent-insensitive) may give extra buckets. Use a shared limiter with a
  per-account or per-network budget for internet-facing admins.
- Anyone who knows an admin's username can keep that account locked out from
  their IP (5 attempts per window). **Behind a reverse proxy without trusted
  proxy headers (uvicorn `--proxy-headers --forwarded-allow-ips`), all clients
  share one IP**: any 30 attempts (successful or not) then lock out every
  admin for 15 minutes. Configure proxy headers.
- The per-client budget is per process, like the in-memory limiter.
- The limiter keeps at most 10 000 keys (least recently used evicted), so
  spraying that many keys can reset a lockout.
- **The bundled common-password list is small** (20 000 entries from
  Dropbox zxcvbn; plan amendment A5) and, with the default 12-character
  minimum, mostly redundant: only 97 entries are 12 characters or longer,
  and about 89 of those are not already refused for being only digits. It does not
  catch passwords leaked later or long but guessable phrases; hosts with
  stricter needs can pass a bigger list (`CommonPasswordValidator(path)`) or
  check against a breach service themselves.
- `ModelUserBackend(password_endpoints=True)` lets any admin set any other
  admin's password, because every admin of that backend holds every
  permission (documented; off by default).
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
| An unsafe request whose session cookie is present but no longer valid (expired, idle, tampered) is `401 not_authenticated` before the token check, with that cookie cleared and an anonymous token issued; nothing runs, as with a `403`. (Its token was bound to the dead session, so it could otherwise only be `403 csrf_failed`, and the UI could not offer to sign in again.) The origin check still runs first; with a valid session the token check is unchanged. | `tests/integration/security/test_session_idle.py::test_an_idle_write_is_401_not_a_csrf_failure`, `::test_a_write_without_a_valid_token_is_still_refused` |
| `SameSite=Lax` session cookie as defense in depth. | `tests/integration/security/test_auth.py` |
| A session or CSRF cookie that appears more than once in a request (planted by a sibling subdomain with `Domain=`) is treated as absent by both the server and the SPA, so a planted value never decides the session or the token (fails closed). | `tests/integration/security/test_auth.py::test_repeated_session_cookie_is_rejected`, `::test_repeated_csrf_cookie_is_rejected`, `frontend/src/lib/cookies.test.ts` |
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
| Many-to-many fields are opt-in (`ModelAdmin.many_to_many`), limited to plain association tables with exact join conditions (the API writes the table directly), validated like the target primary key (distinct, at most `max_items`, every key must exist), replaced atomically in the write's transaction, and refused when the stored set is truncated. A lost race (duplicate pair, foreign-key violation) is 409, never 500. Reads use explicit bounded queries (no lazy loading) and chunked `IN` lists. | `tests/unit/introspection/test_many.py`, `tests/unit/test_many_to_many_options.py`, `tests/integration/api/test_many_to_many.py` (SQLite with foreign keys on and off, PostgreSQL) |
| `can_create` / `can_edit` / `can_delete` enforced server-side (403, before reading the body), not only hidden in the UI. With a permission backend the permission is needed too (T9). | `tests/integration/api/test_write.py`, `tests/integration/security/test_authorization.py` |
| Account safety (ADR-0009; public `FlagAccountGuard` since ADR-0011): when the user model of `ModelUserBackend` is registered, an admin cannot change their own sign-in flags or delete their own row (409 `self_lockout`), and no write can remove the last active admin (409 `last_admin`). The last-admin check runs for every write that could remove an admin (decided from the request, not the possibly stale loaded row), locks the active admin rows (`FOR UPDATE`) and re-reads the remaining active admins with a locking read after the flush, in the same transaction, so concurrent removals cannot both succeed; the loser of a lock race gets 409, never 500. Other mappings of the user table are refused at `register()`. | `tests/unit/auth/test_account_guard.py`, `tests/unit/auth/test_account_guard_mappings.py`, `tests/integration/security/test_account_guard.py`, `tests/integration/security/test_account_guard_servers.py` (PostgreSQL 17 and MySQL 8.4 CI jobs, each at READ COMMITTED, REPEATABLE READ and SERIALIZABLE), `tests/unit/api/test_db_errors.py` |
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
| List view state read from the URL (`page`, `q`, `ordering`, `filter[...]`) is validated against the model metadata before it is sent: unknown fields, values and malformed input are dropped (defence in depth; the server stays authoritative). | `frontend/src/features/list/query.test.ts`, `frontend/e2e/list.spec.ts` |
| Forms validate with the server's write rules before sending and send only changed fields on edit; readonly, create-only and excluded fields are never sent (the server's `extra="forbid"` stays authoritative). Dialogs use the native `<dialog>` element, not scroll-lock libraries that inject `<style>`. | `frontend/src/features/form/codec.test.ts`, `frontend/src/features/record/RecordPages.test.tsx`, `frontend/e2e/forms.spec.ts` |
| Frontend dependencies must not inject `<style>`/`<script>` elements or probe `eval` at runtime (CSP blocks and reports them): toasts are an in-house component, and zod runs with `jitless: true`. E2E records every `securitypolicyviolation` event, including blocked attempts a library swallows. | `frontend/src/components/ui/toaster.test.tsx`, `frontend/src/lib/zod-setup.test.ts`, `frontend/e2e/smoke.spec.ts` |

### T7. Secret management

| Control | Tests |
|---|---|
| No secret ships with the package or repo; gitleaks runs in pre-commit. | pre-commit |
| Missing, non-string, short (< 32 chars; < 43 if hand-written charset or word passphrase), placeholder, sequential/keyboard-run, low-diversity or whitespace-padded secret ⇒ `ConfigurationError` at startup; the value never appears in messages, exception chains or `repr`. False rejection of generated keys (token_urlsafe, token_hex, base64, Django-style) is negligible (< 1e-7 per key) and covered by a seeded regression test. | `tests/unit/security/test_secret.py`, `tests/unit/test_config.py` |
| Purpose-specific key derivation: sessions use itsdangerous with salt `faststudio.session` and HMAC-SHA256; CSRF tokens use an HMAC key derived with label `faststudio.csrf`. | `tests/unit/auth/test_tokens.py::test_session_and_csrf_keys_are_separate`, `::test_session_signature_uses_sha256` |

### T8. Supply chain

Dependabot, pip-audit, pnpm audit, CodeQL, SHA-pinned GitHub Actions, PyPI
Trusted Publishing (OIDC, no long-lived tokens). The release workflow re-runs
the full gate (lint, types, tests, bandit, both audits) on the tagged commit,
uses no dependency caches, does not persist checkout credentials and pins the
build backend; publishing to PyPI needs the `pypi` environment (required
reviewer, `v*` tags only). Minimum dependency versions are tested in CI;
`starlette>=0.49.1` excludes the Range-header DoS (CVE-2025-62727).

### T9. Authorization (ADR-0011)

Attacker: a signed-in admin with limited permissions who tries to read or
change models they were not granted, or to grant themselves (or an
accomplice) more than they hold. Without a permission backend every admin
holds every permission (v0.1 behaviour, 0 extra queries).

| Control | Tests |
|---|---|
| Permissions are resolved once per request through the backend's optional, namespaced `faststudio_capabilities` (validated at startup; nothing else on a backend is inspected; a backend still implementing 0.1.1's private guard methods fails startup instead of silently losing its guard). A malformed result is a 500, never a guess. | `tests/unit/auth/test_capabilities.py`, `tests/integration/security/test_authorization.py` |
| Every model route resolves permissions and asks the `ModelAdmin` hooks before reading the body: list and retrieve need view, choices need create or edit on the model and view on the target, writes need their action (object-level for edit and delete), link counts need delete. A hook allows only by returning `True`; an exception is a 500. A test enumerates the mounted routes and fails if one does not resolve permissions; a matrix covers route × user × missing permission. | `tests/integration/security/test_authorization.py` |
| `/meta` lists only viewable models. An object-level view refusal answers 404 like a missing record (no existence oracle), on retrieve, edit, delete and link counts alike; edit and delete refusals of a visible record answer 403. | `tests/integration/security/test_authorization.py` |
| Related models (A1): labels of foreign keys and many-to-many keys whose target the admin cannot view fall back to the key and run no query; `/meta` hides the target and marks the field readonly; writing such a field is refused like a readonly field (422 `extra_forbidden`, before the existence check), so an admin cannot probe which keys exist in a denied model. Link counts leave out fields of hidden models. | `tests/integration/security/test_authorization.py` |
| Create without view returns a minimal `Row` (primary key and the submitted fields): no labels or server-generated values of a model the admin may not view. | `tests/integration/security/test_authorization.py` |
| **Escalation rules**, enforced by core on create, update and delete for admins who do not hold `ALL`, before the account guard (403): only `ALL` may change the superuser-like flag or edit or delete an account holding `ALL`; the codenames a write could give anyone (user and group grants, membership, reverse sides, renaming a permission) must be held by the actor. Computed from the write's intent with a conservative closed form (fixed number of queries), after the record lock and with the affected group and user rows locked `FOR UPDATE` in primary-key order. The target account is re-read under a lock before the flag and `ALL` checks; an account the backend does not report is treated as holding `ALL`. Registering another mapping of a declared user, group, permission or association table, or a writable many-to-many over an association table that the backend's `PermissionSchema` does not declare, fails at `register()`; a backend with permissions but no schema logs a warning (grants are then unchecked). | `tests/integration/security/test_escalation.py` (SQLite, PostgreSQL), `tests/unit/auth/test_permission_schema.py` |
| `contrib.auth`: any active user may sign in, so the tables hold staff accounts only (documented). Usernames are unique in a normalized form (NFKC, case-folded) on every database, so look-alike accounts cannot be created. New users get an unusable password. `password_hash` and `session_token` are declared secret by the account guard: registering an admin for the user model fails unless both are excluded (subclasses of the default admins included). The last active superuser cannot be removed; every user/group/permission side is declared to the escalation rules. | `tests/integration/contrib/`, `tests/unit/test_contrib_auth_backend.py` |
| Query budget: 0 extra queries without a permission backend or for superusers, exactly 1 otherwise, independent of the number of models and hooks; escalation checks add queries only on writes to users, groups and permissions. | `tests/integration/api/test_query_budget.py`, `tests/integration/security/test_authorization.py` |

**Object-level hooks do not filter lists or choices.** `has_view_permission(request, obj)`
hides a record from retrieve only; rows still appear in lists and choices
until a list-query hook exists (v0.3). Do not rely on it to hide rows.

Model identities are not secret: a model the admin may not view answers 403,
an unknown one 404. Deleting a record needs only the delete permission on its
model, also when it removes many-to-many links that other models' fields hold
(removals never escalate). Permission changes take effect on the next
request; they do not end sessions.

## Known limitations (v0.1.0)

- A repeated session or CSRF cookie is refused (T3). Besides a sibling
  subdomain planting one, this happens when an old cookie for a previous
  mount path is still in the browser: after changing `base_url` or a proxy
  prefix, admins may need to clear the site's cookies. FastStudio logs a
  warning naming the cookie.
- **Same-origin exposure.** The session cookie is scoped to `base_url`, but
  a cookie path is not a security boundary: script running anywhere on the
  host's origin (an XSS in the host app) can read admin data with a
  same-origin `fetch`. Writes stay protected (the session-bound CSRF token is
  not readable from there). If the host serves untrusted or user-generated
  content, mount the admin on its own subdomain.

- **Logout only clears the browser's cookie.** Sessions are stateless signed
  cookies (ADR-0004): the server keeps no session list, so signing out cannot
  invalidate a copy of the cookie. A copied or stolen session cookie stays
  valid until `session_max_age` after sign-in (default 8 hours; absolute)
  unless the user's password or active/admin flags change, or the user
  signs out everywhere, each of which changes `auth_version` and revokes
  every session of that user (a custom backend revokes sessions when its
  own `auth_version` changes). With `session_idle_timeout`, a cookie that
  is left unused also expires; one that an attacker keeps using does not,
  until `session_max_age` or "sign out everywhere". Mitigations: `HttpOnly`
  and `Secure` cookies, a short `session_max_age`, an idle timeout, "sign
  out everywhere" (backends with `session_revocation`), changing the
  password after a suspected leak, and rotating `FASTSTUDIO_SECRET_KEY`,
  which signs everyone out at once.
  Planned: a server-side session store with per-session revocation in v0.3.
- Without a permission backend every admin can access every registered
  model; object-level permission hooks do not filter lists or choices (T9).
- The account-safety guard (ADR-0009) only covers writes through the admin
  API, with `ModelUserBackend` or a backend that provides the
  `account_guard` capability (for example `FlagAccountGuard`). Host code, direct database
  changes, and database-only `ON DELETE CASCADE` foreign keys from other
  tables (no ORM relationship, so the delete check cannot see them) can still
  remove the last admin; recover with `restore_admin.py`
  (docs/getting-started.md).
- After a successful commit, the response is built from a fresh read of the
  row. If that read fails (the row was deleted right after the commit, or a
  SQLite writer holds the lock past the busy timeout), the client gets an
  error although the write was saved.
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
- Read-API cost for authenticated admins: deep pages use `OFFSET`, capped
  below `max_list_offset` rows (default 10 000; configurable up to
  10 000 000), every list runs a `COUNT(*)`, contains
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
