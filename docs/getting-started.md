# Getting started

> Targets the v0.1.0 API. Until it is released, `examples/basic/` on `main`
> is the source of truth.

## 1. Install

```bash
pip install faststudio
# plus an async driver, e.g.
pip install aiosqlite   # or asyncpg, aiomysql
```

## 2. Prepare a user table for admins

FastStudio's built-in `ModelUserBackend` reads admins from **your** user model.
It needs a username column, an argon2 password hash column, and (by default)
`is_active` and `is_admin` boolean columns. Column names are configurable.

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
```

Only rows with `is_active` **and** `is_admin` true can sign in.

## 3. Mount the admin

```python
from faststudio import Admin, ModelAdmin, ModelUserBackend

admin = Admin(app, engine=engine, auth_backend=ModelUserBackend(User))


@admin.register
class UserAdmin(ModelAdmin, model=User):
    list_display = ["id", "username", "is_active", "is_admin"]
    search_fields = ["username"]
    list_filter = ["is_active", "is_admin"]
    exclude = ["password_hash"]
```

Always `exclude` credential columns.

## 4. Create the first admin

```python
from faststudio import hash_password

async with session_maker() as session:
    session.add(
        User(username="admin", password_hash=hash_password("a long passphrase"), is_admin=True)
    )
    await session.commit()
```

## 5. Run

```bash
export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/admin>.
