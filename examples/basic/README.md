# Example: a small shop back office

A FastAPI app with four SQLAlchemy 2.0 models (users, categories, products,
tasks) that between them use every field type FastStudio maps: strings, text,
integers, decimals, booleans, enums, dates, timezone-aware datetimes, JSON,
UUIDs and foreign keys. On first start the database is filled with demo data.

## Run it

From the repository root:

```bash
# In a clone of the repository (the example is not part of the package).
# `uv sync` installs faststudio from source, so build the UI once:
uv sync
pnpm -C frontend install && pnpm -C frontend build

export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uv run python -m examples.basic.create_admin admin   # asks for a password (12+ characters)
uv run python -m examples.basic                       # http://127.0.0.1:8000/admin
```

`uv run uvicorn examples.basic.app:create_app --factory --reload` works too. The database is
`./example.db`; set `FASTSTUDIO_EXAMPLE_DATABASE_URL` to use another one
(any SQLAlchemy async URL, e.g. `postgresql+asyncpg://...`).

## What to look at

- `app.py`: one `ModelAdmin` per model. `UserAdmin` excludes the password
  hash and disables creating users from the admin (accounts and passwords come
  from `create_admin`); `ProductAdmin` shows search, filters, default ordering
  and page size.
- `models.py`: the admin's sign-in uses the app's own `User` model through
  `ModelUserBackend` (`username`, `password_hash`, `is_active`, `is_admin`).
- Deleting a category that still has products is refused (`409`): FastStudio
  never lets ORM cascades change rows of other models.
- All admins are equal here: any admin can activate, deactivate, promote or
  delete accounts (including their own; `create_admin` restores access). For a
  stricter setup add `"is_admin"` and `"is_active"` to `UserAdmin.readonly_fields`.
- Session cookies are `Secure`. Browsers accept them on `http://127.0.0.1`
  and `http://localhost`; anywhere else, serve the app over HTTPS rather than
  turning `secure_cookies` off.

## Throwaway mode

```bash
FASTSTUDIO_EXAMPLE_ADMIN_USERNAME=demo FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD='a long passphrase' \
  uv run python -m examples.basic --ephemeral
```

`--ephemeral` uses a temporary database that is deleted on exit and creates
the admin from those variables. The Playwright suite runs the example this
way. Never use `--ephemeral` or its variables for real deployments.
