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
| `session_max_age` | `timedelta` | 8 h | – | Absolute session lifetime; at least 60 seconds. |
| `secure_cookies` | `bool` | `True` | – | `Secure` cookie flag. Browsers accept secure cookies on `http://localhost`, so keep this on for local dev too. `False` logs a warning at startup. |
| `max_page_size` | `int` | `100` | – | Hard cap for list requests and `ModelAdmin.page_size`; 1–1000. |
| `rate_limiter` *(coming in M6, before v0.1.0)* | `RateLimiter` | `InMemoryRateLimiter()` | – | Login throttling: 5 attempts / 15 min per client IP + username. In-memory is per process; use a shared backend with multiple workers. |
| `show_powered_by` | `bool` | `True` | – | Footer credit. |

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
| `icon` | `None` | [lucide](https://lucide.dev/icons) icon name, e.g. `"users-round"` |
| `list_display` | PK + next 4 visible columns | columns shown in the list |
| `search_fields` | `()` | string/text columns only (not enums), case-insensitive contains |
| `list_filter` | `()` | boolean or enum columns |
| `ordering` | `()` | default sort, e.g. `["-created_at", "email"]` |
| `page_size` | `25` (or `max_page_size` if smaller) | 1 … `Admin(max_page_size=...)`; an explicit larger value is an error |
| `readonly_fields` | `()` | shown, never writable |
| `exclude` | `()` | never shown, searched, filtered, sorted or writable; cannot appear in any other option; the primary key cannot be excluded; every attribute mapped to an excluded column must be excluded too |
| `column_labels` | `{}` | `{field: label}` display labels |
| `can_create` / `can_edit` / `can_delete` | `True` | per-model permissions (`bool`) |

List options must be lists or tuples: `search_fields = "email"` is an error
(use `["email"]`). Composite primary keys are not supported yet.
Joined-table inheritance models are supported. Attributes defined by SQL
expressions or by columns of other tables are not fields. Columns whose type
depends on the database dialect (`with_variant`, `TypeDecorator` overriding
`load_dialect_impl`) cannot be used in `search_fields` or `list_filter`.
