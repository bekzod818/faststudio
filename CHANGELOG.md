# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While in `0.x`, minor releases may contain breaking changes; they are always
listed under **Changed** or **Removed** with migration notes.

## [Unreleased]

### Added

- Many-to-many fields (ADR-0010). `ModelAdmin.many_to_many` opts in
  relationships over a plain association table, edited as a list of target
  keys. `ModelAdmin.many_to_many_limits` sets the most keys per field
  (default 500, at most 10 000). Both are validated at registration.
- API contract (additive, `schema_version` stays `"1"`):
  - `FieldType` `"many_to_many"`;
  - `FieldMeta.max_items`;
  - `Row.many_labels` and `Row.truncated`;
  - the choices endpoint for many-to-many fields;
  - `GET /models/{identity}/items/{pk}/links`: how many many-to-many links
    deleting the record would remove, per field (`LinkCountsResponse`);
  - a documented forward-compatibility rule for clients.
- Admin UI: many-to-many fields are edited with a searchable multi-select
  (removable chips, keyboard support, further pages loaded on scroll). Fields
  truncated on a record are shown read-only with an explanation and are
  never sent. The delete confirmation lists the links the delete removes.
- The example app has `Tag` and a `Task.tags` many-to-many field.
- Authorization (ADR-0011):
  - backend capabilities: `faststudio_capabilities` returning
    `BackendCapabilities`, with `PermissionBackend` and `PermissionSchema`
    in `faststudio.auth.capabilities`;
  - the public account guard in `faststudio.auth.guard`, and
    `FlagAccountGuard`;
  - async permission hooks on `ModelAdmin`;
  - `ModelAdmin.extra_permissions`;
  - `faststudio.has_perm` and `faststudio.ALL`.
- Every route is authorized per model:
  - `/meta` lists only viewable models;
  - labels and choices of models the admin may not view are withheld;
  - create without view returns a minimal `Row`.
- Escalation rules: nobody grants a permission they do not hold, whichever
  side of a relationship the write comes from. Only admins holding every
  permission may change the superuser-like flag or touch such accounts.
- API contract (additive): `PermissionsMeta.view`, `AccountMeta.admin_flag`.
- Admin UI: a "Not found or no access" page.
- `faststudio.contrib.auth`: `AuthModels(Base)` (users, groups,
  permissions on your declarative base), `DatabaseAuthBackend` (sign-in,
  superusers, per-user and group permissions, escalation rules, passwords),
  and the users/groups/permissions admins (`user_admin`, `group_admin`,
  `permission_admin` to customize). For admin staff accounts only.
- The `faststudio` command line (ADR-0012): `createadmin`,
  `changepassword`, `syncpermissions` (`--dry-run`, `--prune`, `--yes`) and
  `checkusers` (`--fix`). Passwords are only read interactively, twice.
  `--app` takes an `Admin`, a FastAPI application with one `Admin` mounted,
  or a factory returning either (e.g. `examples.basic.app:create_app`).
- `Admin(sync_permissions_on_startup=True)`. Several processes starting at
  once sync without errors or log noise (a deadlock victim is retried after
  a short backoff).
- `AccountManager.find_account`, `required_fields` and `create_admin`;
  `BackendCapabilities.username_audit` (`UsernameAudit`, `AuditedAccount`);
  `PermissionSchema.name_field`.
- Public password helpers in `faststudio.auth.passwords` for custom
  backends: `hash_password_async`, `verify_password_async`,
  `dummy_verify_async`, `prepare_dummy_hash`, `is_password_hash` (with the
  existing `hash_password`).
- `AccountGuard.secret_fields` (enforced at `register()`; a required member
  of the not yet released `AccountGuard` protocol, so custom guards written
  against earlier development builds must add it) and
  `BackendCapabilities.register_admins`.
- Passwords (ADR-0011, ADR-0013):
  - validators in `faststudio.auth.validators` (`DEFAULT_VALIDATORS`:
    length, similarity to name and email, not only digits;
    `CommonPasswordValidator` for a list you provide; FastStudio bundles
    none);
  - the `accounts` capability (`AccountManager`) and `password_endpoints`;
  - `ModelUserBackend(password_validators=..., password_endpoints=False)`;
  - `POST /auth/password` and `POST /models/{identity}/items/{pk}/password`;
  - "Change password" and "Set password" in the UI;
  - contract (additive): `MetaResponse.capabilities`,
    `AccountMeta.set_password`.
- Sessions (ADR-0013):
  - `Admin(session_idle_timeout=...)` (off by default): sessions also end
    after that long without a request, and active ones slide. Off, the
    session cookie is unchanged from 0.1.x. Enable it only once every worker
    runs 0.2 (0.1 workers refuse the longer cookie);
  - `Admin(session_max_age=...)` also accepts int seconds;
  - "Sign out everywhere": `POST /auth/sign-out-everywhere`, a header button,
    the `session_revocation` capability (`SessionRevocation` in
    `faststudio.auth.capabilities`) and
    `MetaResponse.capabilities.sign_out_everywhere`. `contrib.auth`
    provides it; `ModelUserBackend(session_token_field=...)` names a string
    column of your user model for it (turning it on signs everyone out once);
  - a save that meets an expired session asks for the password in place and
    retries with the original input.

- Tested databases are documented (SQLite with Python 3.11–3.13,
  PostgreSQL 17, MySQL 8.4 LTS with `aiomysql[rsa]`); CI runs the MySQL
  suite.

### Changed

- A write (POST, PATCH, DELETE) sent with an expired session cookie now
  gets `401 not_authenticated` instead of `403 csrf_failed`, with the dead
  cookie cleared; nothing runs in either case.
- The README and getting-started create the first admin with
  `faststudio createadmin`; the v0.1 `create_admin.py` script is kept under
  "Without the CLI".
- Auth backends that still implement 0.1.1's private account-guard methods
  without `faststudio_capabilities` fail at startup instead of silently
  losing their guard. `ModelUserBackend` provides its guard through
  `faststudio_capabilities`; its private `guards`, `before_write`,
  `check_model` and `protected_fields` methods are gone, so a subclass that
  overrode them must move its rules into an `AccountGuard` (startup logs a
  warning while such methods exist). Creates now reach the account guard
  (`WriteIntent.action == "create"`).
- Deleting a record removes the links of its opted-in many-to-many fields,
  and of opted-in fields of other models pointing at it, instead of
  answering `409`. Relationships that are not opted in behave as before.
- Foreign-key labels are loaded in chunks of at most 500 keys per query.
- Many-to-many writes lock the record's row with `SELECT ... FOR UPDATE` on
  PostgreSQL and MySQL/MariaDB, so host `ON UPDATE` triggers never fire when
  only links change. On SQLite a no-change `UPDATE` takes the write lock,
  so SQLite triggers do fire. Under PostgreSQL REPEATABLE READ, concurrent
  link edits of one record may merge (documented).

## [0.1.1] - 2026-11-24

### Added

- `Admin(max_list_offset=...)` and the matching `max_list_offset` field in the
  SPA's runtime config.
- Error codes `self_lockout` and `last_admin` in the API contract.
- `ModelMeta.account` (additive, `schema_version` stays `"1"`): on the model
  that holds the admins' accounts it lists the fields an admin cannot change
  on their own record. The UI shows them read-only there and hides the delete
  button; the server enforces the rule regardless.

### Changed

- Lists and relation pickers stop at `max_list_offset` rows (default
  10 000): a page is reachable while `(page - 1) * page_size` is below it,
  and pages past that now return `400 invalid_query`. Before, pages up to
  100 000 were accepted (an `OFFSET` of up to 10 million rows). Response
  shapes are unchanged. **Migration:** pass
  `Admin(max_list_offset=...)` (up to 10 000 000) to restore deeper paging.
- With `ModelUserBackend`, `Admin.register()` now raises `ConfigurationError`
  for a model that maps the user model's table without being the user model
  or a subclass of it (an inheritance base class, a sibling subclass sharing
  the table, or a second class on the same table), because writes through it
  would bypass the account-safety checks. **Migration:** register the user
  model itself (or a subclass of it).

### Fixed

- An admin could lock themselves out: clearing their own `is_admin` /
  `is_active` flag or deleting their own row in the registered user model
  succeeded, and every later request returned 401. These writes now return
  `409 self_lockout`, and no write can remove the last active admin
  (`409 last_admin`, checked atomically in the write's transaction; ADR-0009).
- Writes that lose a race to a concurrent request (SQLite "database is
  locked", serialization failures, deadlocks, or an update of a row deleted
  meanwhile) return `409 conflict` instead of `500`.

## [0.1.0] - 2026-11-24

### Added

- Project scaffold: packaging with a wheel build hook that bundles the React SPA,
  CI (lint, mypy, tests on Python 3.11–3.13, security scans, wheel smoke test,
  Playwright E2E), release workflow with PyPI Trusted Publishing, CodeQL and
  Dependabot.
- Architecture docs, threat model and ADRs 0001–0008.
- `Admin` validates all options (values and types) at startup and raises
  `ConfigurationError` on misconfiguration: exactly one of `engine` (must be an
  `AsyncEngine`) or `session_maker`, an `AuthBackend` instance with async
  methods, title, `base_url`, `session_max_age` and `max_page_size` bounds.
- Secret key resolution from `secret_key=` or `FASTSTUDIO_SECRET_KEY`; startup
  fails if it is missing, too short, a known placeholder, sequential or a
  keyboard run, low diversity, hand-written and under 43 characters, or has
  surrounding whitespace. The secret never appears in error messages or `repr`.
- Public `AuthBackend` protocol and `AuthenticatedUser` dataclass with a
  required, non-empty `auth_version` for session revocation.
- `ModelAdmin` declarative options and `Admin.register()` (also usable as a
  class decorator). Registration validates everything at startup: mapped
  model, single-column primary key, unique identity and model, field names
  (with the list of available fields in the error), text-only
  `search_fields`, boolean/enum-only `list_filter`, `ordering` syntax,
  `page_size` within `max_page_size`, and that `exclude`d fields are not
  displayed, searched, filtered, sorted, made readonly or labelled (including
  through another attribute mapped to the same column). Unknown public class
  attributes are rejected so a misspelled option never fails open; typos and
  Django/SQLAdmin option names get a suggestion. Joined-table inheritance is
  supported. Visible fields with sensitive-looking names log a warning.
- Introspection of every visible column into a field description: type
  (`string`, `text`, `integer`, `float`, `decimal`, `boolean`, `date`,
  `datetime`, `enum`, `json`, `uuid`, `foreign_key`, `unsupported`),
  label, nullable/required/readonly flags, JSON-safe default, max length,
  enum choices, many-to-one relation target, timezone, precision/scale and
  help text from the column comment, integer ranges, and a `create_only` flag
  for natural primary keys. Writability fails closed: database- or
  SQLAlchemy-maintained columns, value-converting `TypeDecorator`s and
  unsupported types are read-only; relations only target primary keys;
  sensitive and unsupported defaults are not published. A warning is logged
  when `can_create` is enabled but a required column can never be supplied.
- Versioned API contract (`schema_version` "1") as frozen Pydantic models
  (`MetaResponse`, `ModelMeta`, `FieldMeta`, `ListResponse`, `Row`,
  `ChoicesResponse`, `UserResponse`, `LoginRequest`, `ErrorResponse`), with
  `ModelMeta` built from registered models (relation targets resolved
  across the registry, preferring the table owner under single-table
  inheritance; sortable-field allowlist computed at registration). Login
  passwords never appear in `repr` or errors, usernames reject control
  characters, error details never echo inputs, and unsafe integer bounds
  are not published.
- `scripts/export_contract.py` exports the contract to a committed,
  deterministic JSON Schema; `pnpm gen:contract` generates
  `frontend/src/api/contract.gen.ts` from it. CI and pre-commit fail on drift.
- `Admin` mounts an isolated sub-application at `base_url`: the bundled SPA
  with history fallback, runtime config injected into `index.html`
  (`SpaConfig`, escaped), hashed assets, a JSON-only `/api` namespace, and
  every error in the contract format (new code `method_not_allowed`; 422s
  list `loc`/`msg`/`type` only; 500s are generic and logged).
- Security headers on every admin response, including redirects and 500s:
  strict CSP, `nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`,
  COOP/CORP, `Permissions-Policy`, HSTS over HTTPS and `Cache-Control`.
- Same-origin guard on every `/api/*` request, including reads, so a
  permissive host CORS policy cannot expose admin data (ADR-0008).
- Works behind path-prefix proxies (`--root-path`): the SPA shell, assets,
  API URLs and the trailing-slash redirect include the prefix.
- Authentication: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`;
  every other API route requires a session. Public `ModelUserBackend`
  (admins from your own user model, argon2id, timing-equalized failures),
  `hash_password()`, `RateLimiter`, `RateLimitDecision` and
  `InMemoryRateLimiter` (default 5 attempts / 15 min per IP + username).
- Signed, HttpOnly, SameSite=Lax session cookies with absolute expiry and
  revocation when a user's password or access changes.
- CSRF protection for every unsafe API request: signed double-submit tokens
  bound to the session, rotated on login and logout.
- Read API (session required): `GET /meta`, `GET /models/{identity}/items`
  (pagination, case-insensitive search, sorting and filters, all validated
  against the `ModelAdmin` allowlists; anything else is `400`),
  `GET /models/{identity}/items/{pk}` and foreign-key
  `GET /models/{identity}/fields/{field}/choices`. Rows carry relation labels
  from visible fields; large integers are sent as strings.
- Write API (session + CSRF required): `POST`, `PATCH` and `DELETE` on
  `/models/{identity}/items`. Bodies are validated by write schemas generated
  at registration (unknown, readonly, excluded, managed and primary-key
  fields rejected with 422), values at least as strictly as the database,
  foreign keys checked, `can_*` flags enforced server-side, integrity errors
  returned as 409, bodies capped at 1 MiB (new error code
  `payload_too_large`).
- `Admin(title=...)` rejects control and invisible formatting characters.
- Playwright E2E now runs the built SPA through the real admin mount and
  fails on any CSP violation.
- Frontend foundation: login page (React Hook Form + Zod, generic errors,
  `next` limited to in-app paths), authenticated layout with sidebar built
  from `/meta`, dashboard of registered models, light/dark/system theme
  (`faststudio:theme`), typed API client that sends the CSRF header on writes
  and returns to login when a session expires mid-use. Toasts use a small
  in-house component because toast libraries that inject `<style>` elements
  violate the admin's strict CSP, and zod runs without its `eval` probe.
  The theme toggle cycles light, dark and system (system follows OS changes).
  Playwright now signs in end to end, covers session expiry, and fails on any
  `securitypolicyviolation` event, unexpected 401 or console error.
- List view: a table per model built from `list_display` with type-aware
  cells (booleans, enum labels, foreign-key labels, localised datetimes,
  exact big integers, truncated text and JSON), sortable headers
  (`aria-sort`), debounced search, boolean/choice filters (including
  "Empty" for nullable fields) and pagination. View state lives in the URL
  and is validated against the model metadata before any request, so
  shared links, reload and the back button work and tampered links never
  produce a `400`. Starting a search adds a history entry (Back undoes it);
  refining it does not. Previous results stay visible while the next page
  loads (with a notice if a refresh fails), and stale requests are cancelled.
- A signed-in admin who opens the login page is sent straight to `next`.
- Create and edit forms generated from the model metadata: one widget per
  field type (text, numbers, decimals, switches, tri-state booleans, enum
  selects, date/datetime pickers, JSON and UUID inputs) and a searchable
  picker for foreign keys backed by the choices endpoint. The browser
  applies the same rules as the server (lengths in characters, integer
  ranges with exact big integers, decimal precision/scale, timezone-aware
  datetimes) and server validation errors appear next to their fields.
  Edits send only changed fields; readonly and create-only fields are
  shown but locked; models with editing disabled are read-only.
- Delete with a confirmation dialog built on the native `<dialog>` element
  (no injected styles, so it works under the strict CSP); refused deletes
  (`409`) are explained. Leaving a form or signing out with unsaved changes
  asks first; deleting the record and session-expiry redirects are never
  blocked.
- Toasts confirm creates, saves and deletes. Records link from the first
  list column; an "Add" button appears when creating is allowed.
- Model pages are loaded on demand, keeping the initial bundle small; a
  page whose code cannot be loaded (e.g. a tab opened before an upgrade)
  offers a reload, and a progress bar shows while pages load.
- `examples/basic`: a runnable shop back office (users, categories,
  products, tasks) covering every supported field type, with demo data, a
  `create_admin` command and a throwaway `--ephemeral` mode. Playwright now
  runs against it, and the wheel smoke test runs it on the installed wheel
  (SPA shell, every referenced asset, sign-in, list, create, delete).

### Security

- Login verifies passwords in worker threads (at most 4 at a time per event
  loop), so login floods no longer block the event loop shared with the host
  application.
- Each client address gets at most 30 login attempts per 15 minutes across
  all usernames (on top of the per-username limit), stopping password
  spraying from one address.
- A session or CSRF cookie sent more than once (planted by a sibling
  subdomain) is refused by the server and the UI.
- Requires `starlette>=0.49.1` (Range-header DoS, CVE-2025-62727),
  `fastapi>=0.120.1` and `pydantic>=2.10`; CI now also tests the minimum
  supported versions.
- Logged request paths are escaped (no terminal control sequences in logs).
- Release workflow re-runs every check on the tagged commit, uses no
  dependency caches and does not persist checkout credentials; the build
  backend is pinned.

### Fixed

- List cells show offset-less values of timezone-aware datetime columns
  (e.g. from SQLite) as UTC, consistent with the edit form; they were shown
  as local time.
- Model display names keep acronyms that contain digits together
  (`E2EUser` -> "E2E users", previously "E2 E users").


[Unreleased]: https://github.com/bekzod818/faststudio/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/bekzod818/faststudio/releases/tag/v0.1.1
[0.1.0]: https://github.com/bekzod818/faststudio/releases/tag/v0.1.0
