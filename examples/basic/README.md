# Example: a small shop back office

A FastAPI app with five SQLAlchemy 2.0 models (users, categories, products,
tasks, tags) that between them use every field type FastStudio maps: strings,
text, integers, decimals, booleans, enums, dates, timezone-aware datetimes,
JSON, UUIDs, foreign keys and a many-to-many field. On first start the
database is filled with demo data.

## Run it

From the repository root:

```bash
# In a clone of the repository (the example is not part of the package).
# `uv sync` installs faststudio from source, so build the UI once:
uv sync
pnpm -C frontend install && pnpm -C frontend build

export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uv run python -m examples.basic   # first start creates the tables and demo data; Ctrl-C
uv run faststudio createadmin --app examples.basic.app:create_app --username admin
uv run python -m examples.basic   # http://127.0.0.1:8000/admin
```

The CLI finds the `Admin` mounted on the app that `create_app()` returns.
`faststudio changepassword admin --app examples.basic.app:create_app` sets a
new password. To restore a locked-out account (re-enable it, give back admin
rights and optionally reset its password), use
`uv run python -m examples.basic.create_admin admin`.

`uv run uvicorn examples.basic.app:create_app --factory --reload` works too. The database is
`./example.db`; set `FASTSTUDIO_EXAMPLE_DATABASE_URL` to use another one
(any SQLAlchemy async URL, e.g. `postgresql+asyncpg://...`).

## What to look at

- `app.py`: one `ModelAdmin` per model. `UserAdmin` excludes the password
  hash and disables creating users from the admin (accounts come from
  `faststudio createadmin`); `ProductAdmin` shows search, filters, default ordering
  and page size; `TaskAdmin` opts its `tags` relationship in with
  `many_to_many` and caps it at 20 tags per task with `many_to_many_limits`.
- Deleting a tag removes it from every task; the confirmation says how many
  links go.
- `models.py`: the admin's sign-in uses the app's own `User` model through
  `ModelUserBackend` (`username`, `password_hash`, `is_active`, `is_admin`).
- Deleting a category that still has products is refused (`409`): FastStudio
  never lets ORM cascades change rows of other models.
- All admins are equal here: any admin can activate, deactivate, promote or
  delete accounts (including their own; `examples.basic.create_admin` restores
  access). For a
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
