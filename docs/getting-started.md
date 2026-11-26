# Getting started

This guide builds the [README quickstart](https://github.com/bekzod818/faststudio/blob/main/README.md#quickstart) step by step:
one file with your model and the admin, one script that creates the first
admin account.

## 1. Install

```bash
pip install faststudio aiosqlite uvicorn
```

FastStudio needs SQLAlchemy 2.0 with an **async** driver: `aiosqlite` for
SQLite, `asyncpg` for PostgreSQL, `aiomysql` for MySQL. `uvicorn` runs the app.

## 2. Your user model and the admin (`main.py`)

FastStudio's built-in `ModelUserBackend` signs admins in from **your** user
model. It needs a username column, an argon2 password hash column and (by
default) `is_active` and `is_admin` booleans; the column names are
configurable. Only rows with `is_active` **and** `is_admin` true can sign in.

Save as `main.py`:

```python
from fastapi import FastAPI
from sqlalchemy import String
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from faststudio import Admin, ModelAdmin, ModelUserBackend


class Base(DeclarativeBase):
    pass


class User(Base):  # your own model: FastStudio signs admins in from it
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)


engine = create_async_engine("sqlite+aiosqlite:///app.db")
app = FastAPI()
# secret_key defaults to the FASTSTUDIO_SECRET_KEY environment variable
admin = Admin(app, engine=engine, auth_backend=ModelUserBackend(User))


@admin.register
class UserAdmin(ModelAdmin, model=User):
    list_display = ["id", "username", "email", "is_active", "is_admin"]
    search_fields = ["username", "email"]
    list_filter = ["is_active", "is_admin"]
    exclude = ["password_hash"]  # never show or accept credentials
    can_create = False  # accounts are created with `faststudio createadmin`


async def create_tables() -> None:  # in a real project, use your migrations
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
```

- `Admin(...)` mounts the admin at `/admin` (`base_url=` changes it) and
  validates everything at startup: a wrong option fails loudly with
  `faststudio.ConfigurationError`.
- Always `exclude` credential columns: they are then never shown, searched or
  accepted. Because the password hash cannot be written from the admin,
  creating users there could not work, so `can_create = False` (FastStudio
  warns at startup otherwise).
- Every option is described in the [configuration reference](https://github.com/bekzod818/faststudio/blob/main/docs/configuration.md).

## 3. Tables and the first admin

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -c "import asyncio, main; asyncio.run(main.create_tables())"
faststudio createadmin --app main:admin
```

`create_tables()` creates the tables (use your migrations, e.g. Alembic, in a
real project). `faststudio createadmin` asks for the username, the `email`
column (it is required and has no default) and the password twice, checks the
password (at least 12 characters, not like the username or email, not only
digits) and creates an active admin. Pass `--username` and
`--set email=...` to skip those questions; the password is only ever asked
interactively. Run it again with another username for a second admin.

## 4. Run

```bash
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/admin> and sign in.

- The secret key signs sessions and CSRF tokens. FastStudio refuses to start
  without one, or with a short or placeholder value. Keep it stable across
  restarts and workers, or everyone is signed out.
- Session cookies are `Secure`. Chrome and Firefox accept them on
  `http://localhost` and `http://127.0.0.1`; everywhere else, serve the app
  over HTTPS.

## Locked out?

FastStudio refuses writes that would lock you out: you cannot clear your own
`is_admin` / `is_active` flag or delete your own account in the admin, and
nobody can remove the last active admin (the API answers `409 self_lockout` or
`409 last_admin`). You can still lose access in other ways, such as a
forgotten password or a change made directly in the database. Restore an
account from a shell that can reach the database.

**Forgot a password?** `faststudio changepassword admin --app main:admin`
sets a new one (asked twice) and signs that account out everywhere.

**Lost the admin flag** (e.g. after editing the database by hand)? The CLI
only manages passwords and new accounts, so restore the flags with a short
script.

Save as `restore_admin.py`:

```python
import asyncio
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from faststudio import hash_password
from main import User, engine


async def restore_admin(username: str) -> None:
    try:
        async with async_sessionmaker(engine)() as session:
            user = await session.scalar(select(User).where(User.username == username))
            if user is None:
                sys.exit(f"No user named {username!r}.")
            user.is_active = True
            user.is_admin = True
            if input("Reset the password too? [y/N] ").strip().lower() == "y":
                user.password_hash = hash_password(getpass.getpass("New password: "))
            await session.commit()
    finally:
        await engine.dispose()


asyncio.run(restore_admin(sys.argv[1]))
```

```bash
python restore_admin.py admin
```

It re-enables the account, gives it admin rights and optionally sets a new
password. When a flag or the password actually changes, the account is signed
out of every existing session. To add a second admin instead, run `faststudio createadmin` with a new
username.

## Without the CLI

The CLI is the supported way to create accounts. If you cannot run it (for
example in a locked-down environment), the v0.1 script still works. Save as
`create_admin.py`:

```python
import asyncio
import getpass

from sqlalchemy.ext.asyncio import async_sessionmaker

from faststudio import hash_password
from main import Base, User, engine


async def create_admin() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            session.add(
                User(
                    username=input("Username: "),
                    email=input("Email: "),
                    password_hash=hash_password(getpass.getpass("Password: ")),
                    is_admin=True,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


asyncio.run(create_admin())
```

It creates the tables and one admin per run, but does not check the password
like the CLI does. These snippets are kept for v0.2 and removed in v0.3.

## A complete example

[`examples/basic`](https://github.com/bekzod818/faststudio/blob/main/examples/basic/README.md) is a runnable app with five
models covering every supported field type and demo data. In a clone of the
repository:

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m examples.basic          # first start: creates the tables; stop it with Ctrl-C
faststudio createadmin --app examples.basic.app:create_app --username admin
python -m examples.basic
```
