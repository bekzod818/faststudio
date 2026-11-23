# Configuration

All options are keyword arguments to `faststudio.Admin`. Environment variables
use the `FASTSTUDIO_` prefix.

| Option | Type | Default | Env var | Description |
|---|---|---|---|---|
| `app` | `FastAPI` | required | – | Host application to mount on. |
| `engine` | `AsyncEngine` | – | – | Async engine; FastStudio creates its own `async_sessionmaker`. |
| `session_maker` | `async_sessionmaker[AsyncSession]` | – | – | Use instead of `engine` to share your session factory. Exactly one is required. |
| `auth_backend` | `AuthBackend` | required | – | e.g. `ModelUserBackend(User)`. |
| `secret_key` | `str` | env | `FASTSTUDIO_SECRET_KEY` | Signs sessions and CSRF tokens. ≥ 32 characters, random; weak or placeholder values fail startup. |
| `title` | `str` | `"FastStudio"` | – | UI title. |
| `base_url` | `str` | `"/admin"` | – | Mount path; must start with `/`, no trailing slash. |
| `session_max_age` | `timedelta` | 8 h | – | Absolute session lifetime. |
| `secure_cookies` | `bool` | `True` | – | `Secure` cookie flag. Browsers accept secure cookies on `http://localhost`, so keep this on for local dev too. |
| `max_page_size` | `int` | `100` | – | Hard cap for list requests. |
| `rate_limiter` | `RateLimiter` | `InMemoryRateLimiter()` | – | Login throttling: 5 attempts / 15 min per client IP + username. In-memory is per process; use a shared backend with multiple workers. |
| `show_powered_by` | `bool` | `True` | – | Footer credit. |

## Generating a secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store it in your secret manager or environment; never commit it.

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
