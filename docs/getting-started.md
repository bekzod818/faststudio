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
    can_create = False  # accounts are created in code (see create_admin.py)
```

- `Admin(...)` mounts the admin at `/admin` (`base_url=` changes it) and
  validates everything at startup: a wrong option fails loudly with
  `faststudio.ConfigurationError`.
- Always `exclude` credential columns: they are then never shown, searched or
  accepted. Because the password hash cannot be written from the admin,
  creating users there could not work, so `can_create = False` (FastStudio
  warns at startup otherwise).
- Every option is described in the [configuration reference](https://github.com/bekzod818/faststudio/blob/main/docs/configuration.md).

## 3. Tables and the first admin (`create_admin.py`)

Save as `create_admin.py`:

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

It creates the tables (use your migrations instead in a real project) and
asks for the username, email and password of the first admin. Run it once per
account: usernames are unique, so repeating one fails. Passwords are
hashed with argon2id by `faststudio.hash_password`.

## 4. Run

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python create_admin.py
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/admin> and sign in.

- The secret key signs sessions and CSRF tokens. FastStudio refuses to start
  without one, or with a short or placeholder value. Keep it stable across
  restarts and workers, or everyone is signed out.
- Session cookies are `Secure`. Chrome and Firefox accept them on
  `http://localhost` and `http://127.0.0.1`; everywhere else, serve the app
  over HTTPS.

## A complete example

[`examples/basic`](https://github.com/bekzod818/faststudio/blob/main/examples/basic/README.md) is a runnable app with four
models covering every supported field type, demo data and a `create_admin`
command. In a clone of the repository:

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m examples.basic.create_admin admin
python -m examples.basic
```
