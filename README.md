<p align="center">
  <!-- Logo placeholder: replace with docs/assets/logo.svg once designed -->
  <strong>FastStudio</strong>
</p>

<p align="center"><em>A modern, beautiful admin studio for FastAPI.</em></p>

<p align="center">
  <a href="https://github.com/bekzod818/faststudio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/bekzod818/faststudio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://codecov.io/gh/bekzod818/faststudio"><img alt="Coverage" src="https://codecov.io/gh/bekzod818/faststudio/branch/main/graph/badge.svg"></a>
  <a href="https://pypi.org/project/faststudio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/faststudio"></a>
  <a href="https://pypi.org/project/faststudio/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/faststudio"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Code style: ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
</p>

> **Status: alpha.** FastStudio is under active development. The public API may
> change in any `0.x` release until `1.0`.

FastStudio adds a polished, Django-Admin-style admin panel to any FastAPI
application backed by SQLAlchemy 2.0 (async). Register your models with a few
lines of declarative Python and get a fast React UI for browsing, searching,
filtering and editing your data. No Node.js required: the UI ships pre-built
inside the Python wheel.

<!-- Screenshot placeholder: docs/assets/screenshot-list.png -->

## Features

- **pip install and go**: the React SPA is bundled in the wheel.
- **Declarative `ModelAdmin`**: `list_display`, `search_fields`, `list_filter`,
  `ordering`, `readonly_fields`, `exclude`, `can_create` / `can_edit` / `can_delete`.
- **Schema-driven UI**: tables and forms are generated from your SQLAlchemy
  models. No per-model frontend code.
- **Server-side everything**: pagination, sorting, search and filters run in
  the database through SQLAlchemy expressions, never string-built SQL.
- **Secure by default**: argon2 password hashing, signed HTTP-only session
  cookies, CSRF protection, login rate limiting, strict security headers and CSP.
- **Typed end to end**: `mypy --strict` clean, ships `py.typed`; the
  frontend's API types are generated from the backend's Pydantic contract.
- Light and dark mode, responsive layout, accessible components.

## Quickstart

```bash
pip install faststudio
```

```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from faststudio import Admin, ModelAdmin, ModelUserBackend
from app.models import User  # your SQLAlchemy 2.0 declarative model

engine = create_async_engine("sqlite+aiosqlite:///app.db")
app = FastAPI()
# secret_key defaults to the FASTSTUDIO_SECRET_KEY environment variable
admin = Admin(app, engine=engine, auth_backend=ModelUserBackend(User))


@admin.register
class UserAdmin(ModelAdmin, model=User):
    list_display = ["id", "email", "is_active", "created_at"]
    search_fields = ["email"]
    list_filter = ["is_active"]
```

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn main:app
# open http://127.0.0.1:8000/admin
```

Create an admin user by storing `faststudio.hash_password("...")` in your user
table's `password_hash` column with `is_admin = True`. See
[docs/getting-started.md](docs/getting-started.md).

> The snippet shows the target v0.1.0 API. Until v0.1.0 is released, follow
> `examples/basic/` on the `main` branch.

## Configuration

| Option (`Admin(...)`) | Env var | Default | Notes |
|---|---|---|---|
| `secret_key` | `FASTSTUDIO_SECRET_KEY` | required | ≥ 32 chars, random. Startup fails if missing or weak. |
| `base_url` | – | `/admin` | Mount path. The UI works under any path. |
| `title` | – | `"FastStudio"` | Shown in the header and browser tab. |
| `session_max_age` | – | 8 hours | Absolute session lifetime. |
| `secure_cookies` | – | `True` | Set `False` only for plain-HTTP development on non-localhost hosts. |
| `max_page_size` | – | `100` | Upper bound for any list request. |
| `rate_limiter` | – | in-memory | Use a shared limiter when running several workers. |
| `show_powered_by` | – | `True` | "Powered by FastStudio" footer. |

Full reference: [docs/configuration.md](docs/configuration.md).

## Security

FastStudio treats the admin as a high-value target. Every API route except
login requires a session; state-changing requests require a CSRF token; search,
filter and sort parameters are validated against the fields you declared;
writes respect `readonly_fields` and `exclude`. Read the
[threat model](docs/threat-model.md) and report vulnerabilities privately as
described in [SECURITY.md](SECURITY.md).

## How it compares

FastStudio stands on the shoulders of excellent existing projects:

- **[SQLAdmin](https://github.com/aminalaee/sqladmin)** is a mature, widely used
  admin for SQLAlchemy built on Starlette with server-rendered Jinja2
  templates. It supports sync and async engines and offers many more features
  than FastStudio does today.
- **[Starlette-Admin](https://github.com/jowilf/starlette-admin)** is a flexible
  admin framework supporting several ORMs/ODMs (SQLAlchemy, SQLModel,
  MongoEngine, ODMantic, Beanie), with file handling and data export, using
  server-rendered templates.

FastStudio takes a different approach: a **single-page React application**
driven by a versioned JSON metadata contract, with a typed REST API between
them. It is narrower in scope (SQLAlchemy 2.0 async only) and younger. If you
need a proven tool today, both projects above are great choices.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Highlights after v0.1.0: relationship editing,
custom actions, file uploads, role-based permissions, audit log, i18n
(English, Uzbek, Russian).

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and
the [architecture overview](docs/architecture.md).

## License

[MIT](LICENSE) © 2026 Bekzod
