# Configuration

`app` is the only positional argument to `faststudio.Admin`; all other options
are keyword-only. Every option is validated at startup: a wrong value or type
raises `faststudio.ConfigurationError`. Environment variables use the
`FASTSTUDIO_` prefix.

| Option | Type | Default | Env var | Description |
|---|---|---|---|---|
| `app` | `FastAPI` | required | – | Host application to mount on. |
| `engine` | `AsyncEngine` | – | – | Async engine; FastStudio creates its own `async_sessionmaker`. |
| `session_maker` | `async_sessionmaker[AsyncSession]` | – | – | Use instead of `engine` to share your session factory. Exactly one is required. |
| `auth_backend` | `AuthBackend` | required | – | An *instance* with async `authenticate()` and `get_user()`, e.g. `ModelUserBackend(User)`. |
| `secret_key` | `str` | env | `FASTSTUDIO_SECRET_KEY` | Signs sessions and CSRF tokens. ≥ 32 characters, random; weak or placeholder values fail startup. |
| `title` | `str` | `"FastStudio"` | – | UI title, 1–100 characters (surrounding whitespace stripped). |
| `base_url` | `str` | `"/admin"` | – | Mount path such as `/admin` or `/back-office/studio`. Segments may use letters, digits, `.`, `_`, `~`, `-`; a trailing `/` is removed. `/`, empty or dot segments, queries, fragments and percent-encoding are rejected. |
| `session_max_age` | `int` (seconds) or `timedelta` | 8 h | – | Absolute session lifetime; at least 60 seconds. |
| `session_idle_timeout` | `int` (seconds), `timedelta` or `None` | `None` (off) | – | Also end a session after this long without a request; 60 seconds up to `session_max_age`. See [Sessions](#sessions). |
| `secure_cookies` | `bool` | `True` | – | `Secure` cookie flag. Browsers accept secure cookies on `http://localhost`, so keep this on for local dev too. `False` logs a warning at startup. |
| `max_page_size` | `int` | `100` | – | Hard cap for list requests and `ModelAdmin.page_size`; 1–1000. |
| `max_list_offset` | `int` | `10_000` | – | Lists and relation pickers never skip this many rows or more; see [Deep pagination](#deep-pagination). 1–10 000 000. |
| `rate_limiter` | `RateLimiter` | `InMemoryRateLimiter()` | – | Login throttling: 5 attempts / 15 min per client IP + username. In-memory is per process; use a shared backend with multiple workers. Independently, each client IP gets at most 30 attempts / 15 min across all usernames (per process). Client IPs must be real: behind a reverse proxy enable trusted proxy headers (`uvicorn --proxy-headers --forwarded-allow-ips=...`). |
| `show_powered_by` | `bool` | `True` | – | Footer credit. |
| `sync_permissions_on_startup` | `bool` | `False` | – | Create missing permissions on the first admin request, as `faststudio syncpermissions` does without `--prune`; needs a permission schema (e.g. `contrib.auth`). A failure is logged and retried. |

## Mounting

`Admin(app, ...)` mounts an isolated sub-application at `base_url` (ADR-0006):
it has its own error handling and security headers, and adds nothing to the
host's OpenAPI schema. Host routes registered on `app` before the admin that
start with `base_url` take precedence, so keep `base_url` exclusive to
FastStudio. Behind a reverse proxy with a path prefix, set the prefix on the
**server** (e.g. `uvicorn --root-path /prefix`), not with the deprecated
`FastAPI(root_path=...)`; the SPA, its assets and API URLs are then rendered
with the prefix. A mismatched setup leaves the admin unreachable.

Host middleware still wraps the admin. In particular a permissive,
credentialed **CORS** policy on the host would normally let other websites
read responses; FastStudio rejects every cross-origin browser request to its
API (including GET) with `403`, so admin data stays same-origin regardless
(ADR-0008). Unhandled admin errors return a generic 500 and are then re-raised
to the host, so your error monitoring sees them.

## Authentication

`ModelUserBackend(model, *, username_field="username",
password_field="password_hash", is_active_field="is_active",
is_admin_field="is_admin", password_validators=DEFAULT_VALIDATORS,
password_endpoints=False, session_token_field=None)` reads admins from your own SQLAlchemy model.
Column names are checked at startup. Only active admins can sign in; pass
`is_admin_field=None` only if every row of that table is an administrator.
Store passwords with `faststudio.hash_password()` (argon2id); rows without a
usable argon2 hash (NULL, other algorithms) cannot sign in. Declare the
username column unique: if several rows match a username, the login is
refused (FastStudio logs a warning at startup when it is not unique).

### Passwords

New passwords set through FastStudio (the HTTP endpoints below, and the CLI
in v0.2) are checked by the backend's validators, after the hard limits (not
empty, at most 1024 characters, no NUL):

```python
from faststudio import ModelUserBackend
from faststudio.auth.validators import (
    CommonPasswordValidator,
    MinimumLengthValidator,
    NumericPasswordValidator,
    UserAttributeSimilarityValidator,
)

backend = ModelUserBackend(
    User,
    password_validators=[
        MinimumLengthValidator(14),
        UserAttributeSimilarityValidator(),  # username and email
        NumericPasswordValidator(),
        CommonPasswordValidator("common-passwords.txt.gz"),  # your own list
    ],
    password_endpoints=True,  # see the warning below
)
```

The default is `DEFAULT_VALIDATORS`: at least 12 characters, not similar to
the username or email, not only digits. **FastStudio ships no list of common
passwords**: we found none whose licence clearly allows redistribution.
`CommonPasswordValidator` reads a file you provide (one password per line,
UTF-8, optionally gzip-compressed; compared case-insensitively). Make sure
you may use the list you choose.

**HTTP password endpoints** are off for `ModelUserBackend` unless
`password_endpoints=True`:

- `POST /auth/password` lets every admin change their own password (the
  current password is required; wrong guesses count against the login rate
  limit). The admin's other sessions are signed out.
- `POST /models/{identity}/items/{pk}/password` sets another account's
  password. It needs every permission. **With `ModelUserBackend` every admin
  holds every permission, so enabling the endpoints lets any admin reset any
  other admin's password.** Enable them only if that is acceptable.

The UI shows "Change password" in the header and "Set password" on account
records when the endpoints are available.

### Sessions

Sessions are signed cookies (`faststudio_session`, HttpOnly, `SameSite=Lax`,
Secure unless `secure_cookies=False`) scoped to the admin path. Changing a
user's password, deactivating them or removing admin rights signs them out
everywhere on their next request. Rotating `FASTSTUDIO_SECRET_KEY` signs
everyone out.

- **Absolute lifetime** (`session_max_age`, 8 hours by default): a session
  ends that long after sign-in, whatever happens.
- **Idle timeout** (`session_idle_timeout`, off by default): a session also
  ends after that long without a request. Active sessions slide: the cookie
  is renewed at most every `min(timeout / 4, 5 minutes)`, keeping its
  session id and its absolute end. The UI does no background polling, so
  only real use keeps a session alive. If a save hits an expired session,
  the UI asks for the password in place and retries the save with the
  original input (kept in memory only). The idle timeout limits cookies left
  behind (an unlocked, abandoned browser); it does not stop someone actively
  using a stolen cookie, which stays valid until `session_max_age` or
  "Sign out everywhere".
- **Sign out everywhere**: a button in the header ends every session of the
  signed-in admin, in every browser. It needs a backend with the
  `session_revocation` capability: `contrib.auth` has it; for
  `ModelUserBackend` pass `session_token_field`:

```python
class User(Base):
    ...
    session_token: Mapped[str | None] = mapped_column(String(64), nullable=True)


backend = ModelUserBackend(User, session_token_field="session_token")
```

The column must be a string of at least 43 characters (or unbounded). Its
value becomes part of every session, so **turning the option on signs
every admin out once**. Rows where it is NULL or empty can still sign in;
the first "Sign out everywhere" stores a random token, and
`faststudio createadmin` sets one. Password changes leave it alone (the
password hash already ends the other sessions). It is a secret field:
exclude it from the user model's `ModelAdmin`, or registration fails.

Custom backends implement `faststudio.AuthBackend` (async `authenticate()` and
`get_user()`, returning `faststudio.AuthenticatedUser`); FastStudio provides
cookies, CSRF protection, expiry and rate limiting around them.

For several workers, pass a shared `rate_limiter` implementing
`faststudio.RateLimiter` (async `hit(key) -> RateLimitDecision` and
`reset(key)`), e.g. backed by Redis.

## Writes and database constraints

Create, edit and delete go through the generated write schemas and a single
transaction per request; integrity errors return `409`. On **SQLite**,
foreign keys are not enforced unless you enable them, e.g.:

```python
from sqlalchemy import event


@event.listens_for(engine.sync_engine, "connect")
def _fk_on(dbapi_connection, _record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
```

FastStudio still checks that a submitted foreign-key value, and every
many-to-many key, exists. With `PRAGMA foreign_keys` off that check is the
**only** guard against links to missing rows, so enable foreign keys in
production. Deleting a row referenced by a table without an ORM
`relationship()` only fails if the database enforces the constraint.

Deleting is refused (`409`) while an ORM `relationship()` the delete would
touch still has related rows (one-to-many, many-to-many, or many-to-one with a
`delete` cascade), so ORM cascades cannot change rows of other models. A row
added concurrently between that check and the delete is not covered: the
ORM would still null or delete it. To leave that decision to the database,
declare the relationship with `passive_deletes=True` and enforce the foreign
key (or an `ON DELETE` rule) in the database.

Registration fails when a readonly column is still writable through another
attribute, or when two writable attributes map to the same column.

In production create the engine with `hide_parameters=True` so that any
SQLAlchemy error logged by your application never contains row values.

## Many-to-many fields

List a `relationship()` in `ModelAdmin.many_to_many` to edit it as a field (a
list of the target's primary keys):

```python
class PostAdmin(ModelAdmin, model=Post):
    many_to_many = ("tags",)
    many_to_many_limits = {"tags": 2_000}  # default 500, at most 10 000
```

- **Plain association tables only.** FastStudio reads and writes the
  `secondary` table directly, so the relationship must meet all of these:
  - the table has exactly two foreign keys, each referencing the
    single-column primary key of one side;
  - every other column has a default;
  - the join conditions are just those two equalities;
  - the target primary key is an integer, string or UUID.

  Anything else (association objects, extra criteria in `primaryjoin` or
  `secondaryjoin`, also on `viewonly` relationships) fails registration with
  the reason. Self-referential relationships work.
- **Opt-in.** Unlisted relationships stay invisible, so upgrading never
  exposes new writable fields.
  - `readonly_fields` and `column_labels` accept the names.
  - `viewonly=True` relationships are read-only.
  - The fields cannot be used in `list_display`, `search_fields`,
    `list_filter` or `ordering`.
- **Bounded.** A record shows at most `max_items` links. When it has more,
  the field is marked truncated and becomes read-only for that record, so a
  partial list is never written back.
- **Unique pairs.** Give the association table a primary key or unique
  constraint on the two foreign keys. FastStudio serializes its own link
  writes per record, but other code writing the table could still store
  duplicate links, so registration warns when the table has none. Reads hide
  duplicates either way.
- **Concurrent writes.** Before changing a record's links, FastStudio locks
  the record's row and reads its current links with a locking read, so
  concurrent link writes to the same record are serialized:
  - **PostgreSQL and MySQL/MariaDB:** `SELECT ... FOR UPDATE`. The row is not
    written, so your `ON UPDATE` triggers (audit, `updated_at`) do not fire
    when only links change. Under READ COMMITTED (PostgreSQL's default),
    InnoDB's REPEATABLE READ and SERIALIZABLE (the second writer gets `409`),
    concurrent link edits of one record never merge.
  - **PostgreSQL REPEATABLE READ:** the second writer keeps its earlier
    snapshot and no error is raised, so two concurrent link edits of the same
    record may merge (and, without a unique pair, store a duplicate row that
    reads hide). A merge can exceed `max_items`, after which the field is
    read-only in the admin until links are removed in the database; the
    second writer may instead get `409`. Use READ COMMITTED or SERIALIZABLE for
    the admin's engine if that matters.
  - **SQLite** has no `FOR UPDATE`: FastStudio takes the database write lock
    with a no-change `UPDATE` of the record's row, so SQLite `ON UPDATE`
    triggers on that table **do** fire when only links change. SQLAlchemy
    `onupdate` defaults are not applied.
- **Deleting** a record removes its opted-in links (both directions for
  self-referential fields, and links of other registered models' opted-in
  fields pointing at it) instead of refusing with `409`. Relationships that
  are not opted in keep the `409` rule above. The admin's delete
  confirmation lists how many links each field loses.
- **In the admin UI** the field is a searchable multi-select: chosen items
  are chips with a remove button, the option list loads further pages as it
  is scrolled, and Enter toggles the highlighted option (Backspace in the
  empty search box removes the last chip). A save sends the field only when
  its set changed, and never for read-only or truncated fields.

## Permissions

Without a permission backend (for example with `ModelUserBackend`) every
signed-in admin may do everything the `ModelAdmin` flags allow, as in v0.1.
A backend can add per-user permissions through its optional
`faststudio_capabilities` (ADR-0011); `faststudio.contrib.auth` (v0.2) will
provide users, groups and permissions out of the box.

**Codenames** are `"<identity>.<action>"` with the actions `view`, `create`,
`edit` and `delete` (`edit` implies `view`), plus your own:

```python
from faststudio import ModelAdmin, has_perm


class ArticleAdmin(ModelAdmin, model=Article):
    extra_permissions = {"publish": "Publish articles"}  # codename "articles.publish"

    @classmethod
    async def has_edit_permission(cls, request, obj=None) -> bool:
        if obj is not None and obj.published and not await has_perm(request, "articles.publish"):
            return False
        return await super().has_edit_permission(request, obj)
```

- **Hooks** are async classmethods: `has_view_permission(request, obj=None)`,
  `has_create_permission(request)`, `has_edit_permission(request, obj=None)`
  and `has_delete_permission(request, obj=None)`. Each defaults to the static
  flag (`can_create`, …) **and** the permission. Return `True` to allow;
  anything else refuses. Registration fails if a hook is not an async
  classmethod.
- **`faststudio.has_perm(request, codename)`** checks one codename. The
  permissions were resolved once for the request, so it runs no query.
- **Object-level checks** (`obj`) run on retrieve, edit and delete. A record
  `has_view_permission(request, obj)` refuses is a 404 for all three (and for
  its link counts); an edit or delete refusal of a visible record is a 403. **They do not filter lists or choices**: do not rely on
  them to hide rows (a list-query hook is planned for v0.3).
- **Related models:** an admin who may not view a model sees its keys instead
  of labels in other models' fields, cannot open its choices, and cannot set
  relations to it (the field is readonly for them).
- **Create or delete without view** works through the API only; the model is
  not listed in the UI.

**Writing a permission backend.** Return a `BackendCapabilities` from a
`faststudio_capabilities` property. `permissions` resolves a user to `ALL` or
a frozenset of codenames (`resolve`, once per request; `resolve_accounts`, for
the escalation rules). Keep each to one query and return `ALL` for
superusers. `resolve_accounts` must return an entry for every requested
account that exists, keyed by the same values (an account it leaves out is
treated as possibly holding `ALL` and cannot be edited by others).
`permission_schema` tells FastStudio where users, groups and permissions are
stored; **without it, grants edited in the admin are not checked** (startup
logs a warning).

```python
from faststudio import ALL, BackendCapabilities, FlagAccountGuard
from faststudio.auth.capabilities import PermissionSchema


class MyBackend:
    @property
    def faststudio_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            account_guard=FlagAccountGuard(
                User,
                "id",
                ("is_active", "is_superuser"),
                admin_flag="is_superuser",
            ),
            permissions=self,
            permission_schema=PermissionSchema(
                user_model=User,
                permission_model=Permission,
                codename_field="codename",
                user_permissions="permissions",
                group_model=Group,
                user_groups="groups",
                group_permissions="permissions",
            ),
        )

    async def resolve(self, session, user): ...
    async def resolve_accounts(self, session, keys): ...
```

**Password helpers for backends** (`faststudio.auth.passwords`, public):
`hash_password` / `hash_password_async` (argon2id), `verify_password_async`,
`is_password_hash`, and `dummy_verify_async` with `prepare_dummy_hash` (call
it at startup) to spend the same time on unknown accounts, as the
`AuthBackend` protocol requires. The async variants run off the event loop.

**Escalation rules.** When users, groups or permissions are edited in the
admin, FastStudio refuses (403) any write by an admin who does not hold every
permission that would change the superuser-like flag, touch an account
holding every permission, or give anyone a codename the admin does not hold,
from either side of a relationship. The check is deliberately conservative:
adding a codename the admin lacks to a group is refused even if every member
already holds it. Declare every writable side in the `PermissionSchema`:
registering a writable many-to-many over a declared association table that
the schema does not name, or another mapping of a declared table (an alias of
the permission table, say), fails at `register()`.

A backend that still implements 0.1.1's private guard methods (`guards`,
`before_write`, `check_model`) without `faststudio_capabilities` fails at
startup: wrap its rules in an `AccountGuard` (or use `FlagAccountGuard`) and
return it as `BackendCapabilities(account_guard=...)`. Creates now reach the
guard too (`WriteIntent.action == "create"`).

## Command line (`faststudio`)

The `faststudio` command manages accounts and permissions. `--app`
(`module.path:attr`, imported from the current directory) names your `Admin`
instance, your FastAPI application, or a zero-argument factory returning
either (e.g. `main:create_app`). For an application, the one `Admin` mounted
on it is used; with none or several mounted, the command stops and lists
them (point `--app` at the `Admin` itself then). The application's lifespan
never runs, and the CLI never creates tables: run your migrations first.

| Command | Does |
|---|---|
| `faststudio createadmin --app main:admin [--username U] [--set FIELD=VALUE ...]` | Creates an active account with every permission (`ModelUserBackend`: its active/admin flags; `contrib.auth`: a superuser). Asks for required columns without a default (e.g. `email`); `--set` gives text columns. |
| `faststudio changepassword USERNAME --app main:admin` | Sets a new password; the account is signed out everywhere. |
| `faststudio syncpermissions --app main:admin [--dry-run] [--prune [--yes]]` | Creates a permission for every `<identity>.<action>` and `extra_permissions` entry, updates names, and lists stale codenames (no registered model produces them, e.g. after renaming an `identity`) and orphaned ones (stale but still granted). One transaction; idempotent. Deletes stale permissions and their grants only with `--prune`, after confirmation or `--yes`. |
| `faststudio checkusers --app main:admin [--fix [--yes]]` | `contrib.auth`: reports usernames whose normalized form drifted and case-insensitive collisions; `--fix` repairs drift that does not collide, after confirmation or `--yes`. |

- **Passwords** are only asked interactively, twice, and checked by the
  backend's validators. They are never read from arguments or environment
  variables; `--yes` only answers confirmations. Without a terminal, a
  command that needs input refuses.
- **Exit codes:** 0 success, 1 the command refused or failed (nothing is
  changed), 2 usage error (bad arguments, `--app` not found, input needed
  without a terminal). Database errors are reported by type only.
- `Admin(..., sync_permissions_on_startup=True)` runs the sync (never
  `--prune`) on the first admin request instead. Several workers or
  replicas starting at once are fine: concurrent inserts of the same
  permission are skipped, and a deadlock victim is retried after a short
  backoff (at most 5 attempts within about 2 seconds), without logging.
  Other failures, lock-wait timeouts included, are logged (type only) and
  retried after 30 seconds; requests are served meanwhile.
- `--app` calls a factory but never starts the application: what its
  lifespan sets up (for example a database URL fetched at startup) is not
  seen. Point `--app` at an `Admin` built with the right engine in that case.

## Users, groups and permissions (`contrib.auth`)

`faststudio.contrib.auth` stores admin accounts, groups and permissions in
tables FastStudio declares on your own SQLAlchemy base:

```python
from sqlalchemy.orm import DeclarativeBase
from faststudio import Admin
from faststudio.contrib.auth import AuthModels, DatabaseAuthBackend


class Base(DeclarativeBase):
    pass


auth = AuthModels(Base)  # faststudio_user, faststudio_group, faststudio_permission, ...
admin = Admin(app, engine=engine, auth_backend=DatabaseAuthBackend(auth))
```

> **These are admin staff accounts, not your application's users.** Every
> active user in these tables can sign in to the admin. Never store your
> application's end users (customers, members) here.

- **Tables.** Create them with your migrations: Alembic autogenerate sees
  them because they live on your `Base` (`table_prefix=` changes the
  `faststudio_` prefix). Association tables cascade deletes.
- **Sign-in.** Any active user may sign in. Usernames are compared in a
  normalized form (NFKC, case-folded): `Admin`, `admin` and full-width
  variants are the same account, and cannot be created twice (409).
  `last_login` is recorded.
- **Permissions.** Superusers hold every permission. Other users hold the
  permissions granted to them and to their groups, resolved with one query
  per request. The escalation rules apply to every edit of users, groups and
  permissions. The last active superuser cannot be deactivated, demoted or
  deleted, and nobody can do that to their own account.
- **Passwords.** New users get an unusable password: they cannot sign in
  until one is set, with "Set password" (by a superuser) or the CLI (v0.2).
  The password endpoints are on. `password_validators=` works as for
  `ModelUserBackend`.
- **Permission rows** follow your registered models (`<identity>.<action>`
  and `extra_permissions`); `faststudio syncpermissions` (v0.2) creates them.
  The permissions admin is read-only.

**Customizing the admins.** By default the users, groups and permissions
admins are registered for you. To change them, turn that off and register
subclasses of the exported defaults:

```python
from faststudio.contrib.auth import group_admin, permission_admin, user_admin

admin = Admin(app, engine=engine, auth_backend=DatabaseAuthBackend(auth, register_admins=False))


class StaffAdmin(user_admin(auth)):
    list_display = ("id", "username", "email", "last_login")


admin.register(StaffAdmin)
admin.register(group_admin(auth))
admin.register(permission_admin(auth))
```

`password_hash` and `session_token` must stay excluded: registration fails
otherwise. Customize only this way: with automatic registration on, the
registered classes are not reachable from your code.

`username_normalized` is kept in sync when `username` is assigned through
the ORM (the admin, the CLI, `user.username = ...`). Core `update()` or bulk
statements bypass it: always change usernames through the ORM. Run
`faststudio checkusers --app main:admin` (for example in CI) to find drift
and case-insensitive collisions; `--fix` repairs what it safely can.

## Deep pagination

Lists page with SQL `OFFSET`, and the database reads and discards every
skipped row, so page 40 000 of a large table costs far more than page 1.
FastStudio therefore stops at `max_list_offset` (default 10 000) rows:

- A page is reachable while its offset, `(page - 1) * page_size`, is **less
  than** `max_list_offset`. The last reachable page is
  `ceil(max_list_offset / page_size)`: with the default cap that is page 400
  at 25 rows per page, page 334 at 30, and page 100 at 100.
- The relation picker (choices endpoint, 20 rows per page) follows the same
  rule: page 500 is its last page by default.
- A request past the last reachable page gets `400 invalid_query`. The UI
  stops its pagination there and tells the admin to narrow the results.

To reach older rows, search, filter or sort the list (for example by newest
first) instead of paging. Raise `max_list_offset` only if your database
handles the deeper scans (an index on the sort column helps), up to
10 000 000. Response shapes do not change.

## Generating a secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store it in your secret manager or environment; never commit it. FastStudio
refuses to start if the key:

- is missing or not a string, or has leading/trailing whitespace;
- is shorter than 32 characters, or shorter than 43 if it looks hand-written
  (characters outside base64/base64url/hex, or a passphrase of 3+ lower- or
  title-case words joined by `-`/`_`);
- contains a placeholder (`changeme`, `secretkey`, `example`, `password`,
  `faststudio`, ... anywhere, or `admin`, `secure`, `super`, `qwerty` as a
  separate word);
- contains a run of 8+ sequential or keyboard-row characters (`abcdefgh`,
  `12345678`, `qwertyui`, also reversed);
- uses fewer than 11 distinct characters.

These checks catch common mistakes but cannot prove randomness: always generate
the key. Rotating the key signs everyone out.

## `ModelAdmin` options

Declare with `class UserAdmin(ModelAdmin, model=User)` and register with
`admin.register(UserAdmin)` or the `@admin.register` decorator. Field names are
the model's **attribute** names (not database column names). All options are
validated by `register()`; mistakes raise `ConfigurationError` naming the class
and option.

**Unknown public class attributes are rejected**, so a misspelled option such
as `exclude_fields` can never silently leave a column exposed. Name your own
class attributes with a leading underscore (`_cache = ...`); methods,
properties and class/static methods are allowed. Misspellings (`list_filters`)
and Django/SQLAdmin names (`list_per_page`, `column_details_exclude_list`,
...) are reported with a suggestion; options FastStudio does not support
(`fields`, `fieldsets`, `list_editable`, ...) say so.

At registration FastStudio logs a warning for visible fields whose names look
sensitive (`password`, `hash`, `secret`, `token`, `api_key`, `salt`, `otp`).
Add them to `exclude`. It also warns when `can_create` is enabled but a
required database column can never be supplied (excluded, readonly or of an
unsupported type).

Field metadata sent to the admin UI includes scalar column **defaults** and
column **comments** (as help text). Don't put secrets in either.
Columns maintained by the database or SQLAlchemy (`onupdate`, `Sequence`,
`Computed`, `Identity`, triggers, version id, polymorphic discriminator) are
read-only automatically. Custom `TypeDecorator`s that convert values are shown
read-only (see `docs/api-contract.md`).

| Option | Default | Notes |
|---|---|---|
| `identity` | table name | URL slug: 1–64 of `a-z 0-9 _ -`, starting with a letter or digit; unique |
| `name` / `name_plural` | humanized model class name / simple English plural | display labels, ≤ 100 chars, no control or invisible formatting characters |
| `icon` | `None` | sidebar icon, one of: `box`, `building-2`, `calendar-days`, `credit-card`, `database`, `file`, `file-text`, `folder`, `globe`, `image`, `key`, `mail`, `map-pin`, `message-square`, `package`, `settings`, `shopping-cart`, `tag`, `user`, `users`. Other names show the default `database` icon |
| `list_display` | PK + next 4 visible columns | columns shown in the list |
| `search_fields` | `()` | string/text columns only (not enums), case-insensitive contains |
| `list_filter` | `()` | boolean or enum columns |
| `ordering` | `()` | default sort, e.g. `["-created_at", "email"]` |
| `page_size` | `25` (or `max_page_size` if smaller) | 1 … `Admin(max_page_size=...)`; an explicit larger value is an error |
| `readonly_fields` | `()` | shown, never writable |
| `exclude` | `()` | never shown, searched, filtered, sorted or writable; cannot appear in any other option; the primary key cannot be excluded; every attribute mapped to an excluded column must be excluded too |
| `column_labels` | `{}` | `{field: label}` display labels |
| `many_to_many` | `()` | many-to-many relationships shown as editable fields; each must be a plain association table (see [Many-to-many fields](#many-to-many-fields)); unlisted relationships stay invisible |
| `many_to_many_limits` | `{}` | most related keys per many-to-many field, default 500, 1–10 000; keys must be listed in `many_to_many` |
| `extra_permissions` | `{}` | custom permissions as `{key: description}`; codename `"<identity>.<key>"`, key `[a-z][a-z0-9_]{0,40}`, not an action, codename ≤ 100 characters (see [Permissions](#permissions)) |
| `can_create` / `can_edit` / `can_delete` | `True` | static switches per model (`bool`); with a permission backend, the admin also needs the permission |

List options must be lists or tuples: `search_fields = "email"` is an error
(use `["email"]`). Composite primary keys are not supported yet.
Joined-table inheritance models are supported. Attributes defined by SQL
expressions or by columns of other tables are not fields. Columns whose type
depends on the database dialect (`with_variant`, `TypeDecorator` overriding
`load_dialect_impl`) cannot be used in `search_fields` or `list_filter`.
