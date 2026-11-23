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
| `max_page_size` | `int` | `100` | – | Hard cap for list requests; 1–1000. |
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

| Option | Default | Notes |
|---|---|---|
| `identity` | table name | URL slug |
| `name` / `name_plural` | from class name | display labels |
| `icon` | `None` | [lucide](https://lucide.dev/icons) icon name |
| `list_display` | PK + first 4 columns | columns shown in the list |
| `search_fields` | `()` | string/text columns, case-insensitive contains |
| `list_filter` | `()` | boolean or enum columns |
| `ordering` | `()` | default sort, e.g. `["-created_at"]` |
| `page_size` | `25` | clamped to `max_page_size` |
| `readonly_fields` | `()` | shown, never writable |
| `exclude` | `()` | never shown, never writable |
| `column_labels` | `{}` | per-field display labels |
| `can_create` / `can_edit` / `can_delete` | `True` | per-model permissions |
