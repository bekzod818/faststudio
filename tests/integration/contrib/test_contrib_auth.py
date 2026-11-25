"""`faststudio.contrib.auth` end to end (ADR-0011 §8, M18b).

Runs on SQLite, and on PostgreSQL when FASTSTUDIO_TEST_POSTGRES_URL points at
a throwaway `*_test` database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from faststudio import Admin, ConfigurationError, ModelAdmin, hash_password
from faststudio.contrib.auth import (
    AuthModels,
    DatabaseAuthBackend,
    group_admin,
    permission_admin,
    user_admin,
)
from tests.factories.contrib_models import AUTH, ContribBase, Note

ORIGIN = "https://testserver"
API = "/admin/api/v1"
PASSWORD = "a long staff passphrase"
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
USERS, GROUPS, PERMS = "faststudio_user", "faststudio_group", "faststudio_permission"


class NoteAdmin(ModelAdmin, model=Note):
    identity = "notes"
    list_display = ("id", "title")


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
            ],
        ),
    ]
)
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if request.param == "postgres":
        name = make_url(POSTGRES_URL).database or ""
        if not name.endswith("_test"):
            pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
        engine = create_async_engine(POSTGRES_URL)
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/contrib.db")

        @event.listens_for(engine.sync_engine, "connect")
        def _foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.drop_all)
        await conn.run_sync(ContribBase.metadata.create_all)
    hashed = hash_password(PASSWORD)
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                AUTH.user(id=1, username="root", password_hash=hashed, is_superuser=True),
                AUTH.user(id=2, username="Staff", email="staff@example.com", password_hash=hashed),
                AUTH.user(id=3, username="newbie"),  # no password yet
                AUTH.user(id=4, username="gone", password_hash=hashed, is_active=False),
                AUTH.permission(id=1, codename="notes.view", name="View notes"),
                AUTH.permission(id=2, codename="notes.edit", name="Edit notes"),
                AUTH.group(id=1, name="readers"),
                Note(id=1, title="hello"),
            ]
        )
        await session.flush()
        await session.execute(insert(AUTH.group_permissions), [{"group_id": 1, "permission_id": 1}])
        if request.param == "postgres":
            for table in (USERS, GROUPS, PERMS, "contrib_notes"):
                await session.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT max(id) FROM {table}))"
                    )
                )
        await session.commit()
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(ContribBase.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def backend() -> DatabaseAuthBackend:
    return DatabaseAuthBackend(AUTH)


@pytest.fixture
def admin(app: FastAPI, db: AsyncEngine, secret_key: str, backend: DatabaseAuthBackend) -> Admin:
    instance = Admin(app, engine=db, auth_backend=backend, secret_key=secret_key)
    instance.register(NoteAdmin)
    return instance


class Client:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def get(self, path: str) -> httpx.Response:
        return await self.http.get(f"{API}{path}")

    async def send(self, method: str, path: str, body: object = None) -> httpx.Response:
        return await self.http.request(method, f"{API}{path}", json=body, headers=self.headers())


SignIn = Callable[..., Awaitable[Client]]


async def _login(http: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    await http.get(f"{API}/auth/me")
    return await http.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        headers={"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN},
    )


@pytest.fixture
async def sign_in(app: FastAPI, admin: Admin) -> AsyncIterator[SignIn]:
    del admin
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str = "root", password: str = PASSWORD) -> Client:
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
            )
            response = await _login(http, username, password)
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


@pytest.fixture
async def attempt(
    app: FastAPI, admin: Admin
) -> AsyncIterator[Callable[[str, str], Awaitable[int]]]:
    del admin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:

        async def _attempt(username: str, password: str) -> int:
            http.cookies.clear()
            return (await _login(http, username, password)).status_code

        yield _attempt


# --------------------------------------------------------------------------- models


def test_tables_prefix_and_cascades() -> None:
    tables = ContribBase.metadata.tables
    for name in (USERS, GROUPS, PERMS, "faststudio_user_groups", "faststudio_group_permissions"):
        assert name in tables
    links = tables["faststudio_user_groups"]
    assert {fk.ondelete for column in links.c for fk in column.foreign_keys} == {"CASCADE"}
    assert tables[USERS].c.username_normalized.unique


def test_auth_models_once_per_base() -> None:
    with pytest.raises(ConfigurationError, match="already called for ContribBase"):
        AuthModels(ContribBase)


@pytest.mark.parametrize(
    ("base", "prefix", "match"),
    [(object, "x_", "declarative base"), (None, "Bad-", "table_prefix")],
)
def test_auth_models_arguments(base: Any, prefix: str, match: str) -> None:
    from sqlalchemy.orm import DeclarativeBase  # noqa: PLC0415

    class Fresh(DeclarativeBase):
        pass

    with pytest.raises(ConfigurationError, match=match):
        AuthModels(base or Fresh, table_prefix=prefix)


def test_new_users_have_an_unusable_password_and_a_session_token() -> None:
    user = AUTH.user(username="x")
    assert user.username_normalized == "x"
    # Column defaults apply at insert; check them through the column metadata.
    columns = ContribBase.metadata.tables[USERS].c
    assert columns.password_hash.default.arg(None).startswith("!")  # type: ignore[union-attr]
    assert len(columns.session_token.default.arg(None)) >= 43  # type: ignore[union-attr]


async def test_new_users_cannot_sign_in_until_a_password_is_set(
    attempt: Callable[[str, str], Awaitable[int]], db: AsyncEngine
) -> None:
    assert await attempt("newbie", "") == 422  # empty password is invalid input
    assert await attempt("newbie", "anything at all") == 401
    async with AsyncSession(db) as session:
        newbie = await session.get(AUTH.user, 3)
        assert newbie is not None
        assert newbie.password_hash.startswith("!")


@pytest.mark.parametrize("username", ["staff", "STAFF", "\uff53\uff54\uff41\uff46\uff46", " Staff"])
async def test_login_is_case_insensitive(
    attempt: Callable[[str, str], Awaitable[int]], username: str
) -> None:
    expected = 401 if username.startswith(" ") else 200
    assert await attempt(username, PASSWORD) == expected


async def test_case_variants_cannot_coexist(sign_in: SignIn) -> None:
    root = await sign_in()
    for username in ("STAFF", "\uff53\uff54\uff41\uff46\uff46"):
        response = await root.send("POST", f"/models/{USERS}/items", {"username": username})
        assert response.status_code == 409, response.text
    for username in ("staff", "STAFF", "\uff53\uff54\uff41\uff46\uff46"):  # rename collisions
        renamed = await root.send("PATCH", f"/models/{USERS}/items/3", {"username": username})
        assert renamed.status_code == 409, username
    fine = await root.send("PATCH", f"/models/{USERS}/items/3", {"username": "Newbie2"})
    assert fine.status_code == 200


async def test_deleting_a_user_cascades_to_memberships(sign_in: SignIn, db: AsyncEngine) -> None:
    root = await sign_in()
    assert (
        await root.send("PATCH", f"/models/{USERS}/items/2", {"groups": [1]})
    ).status_code == 200
    assert (await root.send("DELETE", f"/models/{USERS}/items/2")).status_code == 204
    async with AsyncSession(db) as session:
        count = select(func.count()).select_from(AUTH.user_groups)
        assert (await session.execute(count)).scalar_one() == 0


# --------------------------------------------------------------------------- backend


async def test_login_records_last_login_and_refuses_inactive_users(
    attempt: Callable[[str, str], Awaitable[int]], db: AsyncEngine
) -> None:
    assert await attempt("gone", PASSWORD) == 401
    assert await attempt("root", "wrong password!!") == 401
    assert await attempt("root", PASSWORD) == 200
    async with AsyncSession(db) as session:
        root = await session.get(AUTH.user, 1)
        assert root is not None
        assert root.last_login is not None


@pytest.mark.parametrize(
    "change",
    [
        {"is_active": False},
        {"is_superuser": True},
        {"session_token": "rotated-token-rotated-token-rotated-token-x"},
        {"password_hash": "changed"},
    ],
)
async def test_auth_version_covers_every_access_field(
    sign_in: SignIn, db: AsyncEngine, change: dict[str, Any]
) -> None:
    staff = await sign_in("staff")
    assert (await staff.get("/auth/me")).status_code == 200
    async with db.begin() as conn:
        await conn.execute(AUTH.user.__table__.update().values(**change).where(AUTH.user.id == 2))  # type: ignore[attr-defined]
    assert (await staff.get("/auth/me")).status_code == 401


async def test_query_budget(sign_in: SignIn, db: AsyncEngine) -> None:
    """get_user is one query; superusers resolve with none, others with one."""
    statements: list[str] = []

    def record(_c: object, _cur: object, statement: str, *args: object) -> None:
        del args
        statements.append(statement)

    root, staff = await sign_in(), await sign_in("staff")
    event.listen(db.sync_engine, "before_cursor_execute", record)
    try:
        await root.get("/meta")
        assert len(statements) == 1  # get_user only
        statements.clear()
        await staff.get("/meta")
        assert len(statements) == 2  # get_user + resolve
    finally:
        event.remove(db.sync_engine, "before_cursor_execute", record)


# --------------------------------------------------------------------------- admins


async def test_registered_admins_and_secret_fields(sign_in: SignIn) -> None:
    root = await sign_in()
    models = {m["identity"]: m for m in (await root.get("/meta")).json()["models"]}
    assert list(models) == [USERS, GROUPS, PERMS, "notes"]
    user_fields = {f["name"]: f for f in models[USERS]["fields"]}
    for secret in ("password_hash", "session_token", "username_normalized"):
        assert secret not in user_fields
    assert user_fields["permissions"]["max_items"] == 10_000
    assert user_fields["last_login"]["readonly"] is True
    assert models[USERS]["account"] == {
        "protected_fields": ["is_active", "is_superuser"],
        "admin_flag": "is_superuser",
        "set_password": True,
    }
    assert models[PERMS]["permissions"] == {
        "view": True,
        "create": False,
        "edit": False,
        "delete": False,
    }
    for path in (f"/models/{USERS}/items", f"/models/{USERS}/items/1"):
        body = (await root.get(path)).text
        assert "password_hash" not in body
        assert "session_token" not in body
        assert "$argon2" not in body


def test_customized_admins_with_register_admins_off(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    """The documented pattern: subclasses of the exported admins."""
    admin = Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH, register_admins=False),
        secret_key=secret_key,
    )
    assert len(admin._registry) == 0

    class StaffAdmin(user_admin(AUTH)):  # type: ignore[misc]
        identity = "staff"
        list_display = ("id", "username", "last_login")

    admin.register(StaffAdmin)
    admin.register(group_admin(AUTH))
    admin.register(permission_admin(AUTH))
    assert [r.identity for r in admin._registry] == ["staff", GROUPS, PERMS]

    class LeakyAdmin(user_admin(AUTH)):  # type: ignore[misc]
        identity = "leaky"
        exclude = ("session_token", "username_normalized")  # password_hash visible

    with pytest.raises(ConfigurationError, match="password_hash must be in `exclude`"):
        admin.register(LeakyAdmin)


# --------------------------------------------------------------------------- end to end


async def test_superuser_grants_a_view_only_group(sign_in: SignIn) -> None:
    root = await sign_in()
    created = await root.send("POST", f"/models/{USERS}/items", {"username": "viewer"})
    assert created.status_code == 201, created.text
    pk = created.json()["pk"]
    assert (
        await root.send("PATCH", f"/models/{USERS}/items/{pk}", {"groups": [1]})
    ).status_code == 200
    password = await root.send(
        "POST", f"/models/{USERS}/items/{pk}/password", {"new_password": "quiet harbour lantern 1"}
    )
    assert password.status_code == 204, password.text

    viewer = await sign_in("viewer", "quiet harbour lantern 1")
    meta = (await viewer.get("/meta")).json()
    assert [m["identity"] for m in meta["models"]] == ["notes"]
    assert meta["models"][0]["permissions"] == {
        "view": True,
        "create": False,
        "edit": False,
        "delete": False,
    }
    assert (await viewer.get("/models/notes/items")).status_code == 200
    assert (await viewer.send("PATCH", "/models/notes/items/1", {"title": "x"})).status_code == 403
    assert (await viewer.get(f"/models/{USERS}/items")).status_code == 403
    # Changing one's own password is open to every staff account.
    own = await viewer.send(
        "POST",
        "/auth/password",
        {"current_password": "quiet harbour lantern 1", "new_password": "another passphrase 2"},
    )
    assert own.status_code == 204


async def test_escalation_through_contrib_sides_is_refused(
    sign_in: SignIn, db: AsyncEngine
) -> None:
    async with db.begin() as conn:  # staff manages users and groups, holds only notes.view
        rows = [
            {"id": 10 + i, "codename": c}
            for i, c in enumerate(
                [
                    f"{USERS}.view",
                    f"{USERS}.edit",
                    f"{GROUPS}.view",
                    f"{GROUPS}.edit",
                    f"{PERMS}.view",
                ]
            )
        ]
        await conn.execute(insert(AUTH.permission.__table__), rows)  # type: ignore[attr-defined]
        await conn.execute(
            insert(AUTH.user_permissions),
            [{"user_id": 2, "permission_id": p} for p in (1, 10, 11, 12, 13, 14)],
        )
    staff = await sign_in("staff")
    attempts = [
        (f"/models/{USERS}/items/3", {"permissions": [2]}),  # notes.edit: not held
        (f"/models/{USERS}/items/3", {"is_superuser": True}),
        (f"/models/{USERS}/items/1", {"email": "x@example.com"}),  # a superuser
        (f"/models/{GROUPS}/items/1", {"permissions": [1, 2]}),
        (f"/models/{USERS}/items/3", {"groups": [1]}),  # fine: readers grants notes.view only
    ]
    statuses = [(await staff.send("PATCH", path, body)).status_code for path, body in attempts]
    assert statuses == [403, 403, 403, 403, 200]


async def test_last_superuser_cannot_be_removed(sign_in: SignIn) -> None:
    root = await sign_in()
    own = await root.send("PATCH", f"/models/{USERS}/items/1", {"is_superuser": False})
    assert own.status_code == 409
    assert own.json()["error"]["code"] == "self_lockout"


async def test_concurrent_writes_on_admin_accounts_never_fail_with_500(
    sign_in: SignIn, db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M17 follow-up: record lock, then the guard's admin locks; a deadlock is a 409."""
    import asyncio  # noqa: PLC0415

    from faststudio.api import write as write_module  # noqa: PLC0415

    async with db.begin() as conn:  # two more active superusers to edit concurrently
        await conn.execute(
            AUTH.user.__table__.update()  # type: ignore[attr-defined]
            .where(AUTH.user.id.in_([3, 4]))
            .values(is_superuser=True, is_active=True)
        )
    first, second = await sign_in(), await sign_in()
    barrier = asyncio.Barrier(2)
    current_links = write_module._current_links

    async def synchronized(*args: Any, **kwargs: Any) -> Any:
        await barrier.wait()
        return await current_links(*args, **kwargs)

    monkeypatch.setattr(write_module, "_current_links", synchronized)
    body = {"groups": [1], "is_active": False}
    results = await asyncio.gather(
        first.send("PATCH", f"/models/{USERS}/items/3", body),
        second.send("PATCH", f"/models/{USERS}/items/4", body),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses in ([200, 200], [200, 409]), [r.text for r in results]


async def test_the_sign_in_key_always_follows_the_username(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    """Even an admin exposing username_normalized cannot make it diverge."""
    admin = Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH, register_admins=False),
        secret_key=secret_key,
    )

    class ExposingAdmin(user_admin(AUTH)):  # type: ignore[misc]
        exclude = ("password_hash", "session_token")  # username_normalized visible, writable

    admin.register(ExposingAdmin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:
        assert (await _login(http, "root", PASSWORD)).status_code == 200
        client = Client(http)
        response = await client.send(
            "PATCH", f"/models/{USERS}/items/2", {"username_normalized": "root2"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["username_normalized"] == "staff"
    async with AsyncSession(db) as session:
        row = await session.get(AUTH.user, 2)
        assert row is not None
        assert row.username_normalized == "staff"


async def test_a_busy_database_does_not_break_sign_in(
    attempt: Callable[[str, str], Awaitable[int]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sqlalchemy.exc import OperationalError  # noqa: PLC0415

    original = AsyncSession.commit
    calls = {"n": 0}

    async def busy(self: AsyncSession) -> None:
        calls["n"] += 1
        if calls["n"] == 1:  # the last_login write
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        await original(self)

    monkeypatch.setattr(AsyncSession, "commit", busy)
    with caplog.at_level("WARNING", logger="faststudio.auth"):
        assert await attempt("root", PASSWORD) == 200
    assert "Could not record last_login (OperationalError)" in caplog.text


def test_any_declarative_base_maps_the_relationships() -> None:
    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415
    from sqlalchemy.orm import DeclarativeBaseNoMeta, MappedAsDataclass  # noqa: PLC0415

    class NoMeta(DeclarativeBaseNoMeta):
        pass

    models = AuthModels(NoMeta, table_prefix="nometa_")
    assert set(sa_inspect(models.user).relationships.keys()) == {"groups", "permissions"}
    assert set(sa_inspect(models.permission).relationships.keys()) == {"groups", "users"}

    class Dataclassy(MappedAsDataclass, DeclarativeBaseNoMeta):
        pass

    with pytest.raises(ConfigurationError, match="MappedAsDataclass"):
        AuthModels(Dataclassy)
