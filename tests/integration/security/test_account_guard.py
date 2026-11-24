"""Admins cannot lock themselves out or remove the last active admin (ADR-0009)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from faststudio import Admin, AuthenticatedUser, ModelAdmin, ModelUserBackend, hash_password
from faststudio.api import write as write_module
from faststudio.auth._guard import PostWriteCheck, WriteIntent
from tests.factories.models import AdminUser, Base, Team

ORIGIN = "https://testserver"
BASE = "/admin/api/v1/models"
PASSWORD = "a long test passphrase"
HASH = hash_password(PASSWORD)


class AdminUserAdmin(ModelAdmin, model=AdminUser):
    list_display = ("id", "username", "is_active", "is_admin")
    exclude = ("password_hash",)


class TeamAdmin(ModelAdmin, model=Team):
    list_display = ("id", "name")


def _engine(path: Path, **connect_args: Any) -> AsyncEngine:
    return create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args=connect_args)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "guard.db"


@pytest.fixture
async def db(db_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = _engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables["admin_users"], Base.metadata.tables["teams"]],
        )
    async with async_sessionmaker(engine)() as session:
        session.add_all(
            [
                AdminUser(id=1, username="alice", password_hash=HASH, is_admin=True),
                AdminUser(id=2, username="bob", password_hash=HASH, is_admin=True),
                AdminUser(id=3, username="carol", password_hash=HASH, is_admin=False),
                Team(id=1, name="Core"),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


def _mount(app: FastAPI, engine: AsyncEngine, secret_key: str) -> ModelUserBackend:
    backend = ModelUserBackend(AdminUser)
    admin = Admin(app, engine=engine, auth_backend=backend, secret_key=secret_key)
    admin.register(AdminUserAdmin)
    admin.register(TeamAdmin)
    return backend


@pytest.fixture
def backend(app: FastAPI, db: AsyncEngine, secret_key: str) -> ModelUserBackend:
    return _mount(app, db, secret_key)


class Client:
    """A signed-in admin: an HTTPS client plus CSRF-aware write helpers."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def patch(self, identity: str, pk: int, body: object) -> httpx.Response:
        url = f"{BASE}/{identity}/items/{pk}"
        return await self.http.patch(url, json=body, headers=self._headers())

    async def delete(self, identity: str, pk: int) -> httpx.Response:
        return await self.http.delete(f"{BASE}/{identity}/items/{pk}", headers=self._headers())

    async def me(self) -> int:
        return (await self.http.get("/admin/api/v1/auth/me")).status_code


@pytest.fixture
async def sign_in(app: FastAPI) -> AsyncIterator[Callable[[str], Awaitable[Client]]]:
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str) -> Client:
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
            )
            await http.get("/admin/api/v1/auth/me")
            token = http.cookies["faststudio_csrftoken"]
            response = await http.post(
                "/admin/api/v1/auth/login",
                json={"username": username, "password": PASSWORD},
                headers={"x-faststudio-csrf": token, "origin": ORIGIN},
            )
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


async def _flags(db: AsyncEngine) -> dict[int, tuple[bool, bool]]:
    async with AsyncSession(db) as session:
        rows = (await session.execute(AdminUser.__table__.select())).all()
    return {row.id: (row.is_active, row.is_admin) for row in rows}


def _code(response: httpx.Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


# ------------------------------------------------------------------ self-lockout


@pytest.mark.usefixtures("backend")
@pytest.mark.parametrize("field", ["is_admin", "is_active"])
async def test_admin_cannot_remove_own_access(
    sign_in: Callable[[str], Awaitable[Client]], db: AsyncEngine, field: str
) -> None:
    alice = await sign_in("alice")
    response = await alice.patch("admin_users", 1, {field: False, "username": "renamed"})
    assert response.status_code == 409
    assert _code(response) == "self_lockout"
    assert "own" in response.json()["error"]["message"]
    assert (await _flags(db))[1] == (True, True)
    async with AsyncSession(db) as session:
        alice_row = await session.get(AdminUser, 1)
        assert alice_row is not None
        assert alice_row.username == "alice"  # nothing from the refused write persisted
    assert await alice.me() == 200  # still signed in


@pytest.mark.usefixtures("backend")
async def test_admin_can_resave_own_record(sign_in: Callable[[str], Awaitable[Client]]) -> None:
    alice = await sign_in("alice")
    body = {"is_admin": True, "is_active": True, "username": "alice2"}
    response = await alice.patch("admin_users", 1, body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["username"] == "alice2"
    assert await alice.me() == 200


@pytest.mark.usefixtures("backend")
async def test_admin_cannot_delete_own_account(
    sign_in: Callable[[str], Awaitable[Client]], db: AsyncEngine
) -> None:
    alice = await sign_in("alice")
    response = await alice.delete("admin_users", 1)
    assert response.status_code == 409
    assert _code(response) == "self_lockout"
    assert 1 in await _flags(db)
    assert await alice.me() == 200


@pytest.mark.usefixtures("backend")
async def test_admin_can_manage_other_accounts(
    sign_in: Callable[[str], Awaitable[Client]], db: AsyncEngine
) -> None:
    alice = await sign_in("alice")
    # Removing other active admins runs the last-admin check, which passes.
    assert (await alice.delete("admin_users", 2)).status_code == 204
    assert (await alice.patch("admin_users", 3, {"is_admin": True})).status_code == 200
    assert (await alice.patch("admin_users", 3, {"is_active": False})).status_code == 200
    assert await _flags(db) == {1: (True, True), 3: (False, True)}


@pytest.mark.usefixtures("backend")
async def test_other_models_are_not_guarded(sign_in: Callable[[str], Awaitable[Client]]) -> None:
    alice = await sign_in("alice")
    assert (await alice.patch("teams", 1, {"name": "Platform"})).status_code == 200
    assert (await alice.delete("teams", 1)).status_code == 204


# ------------------------------------------------------------------ concurrency


async def test_concurrent_demotions_leave_one_admin(
    sign_in: Callable[[str], Awaitable[Client]],
    backend: ModelUserBackend,
    db: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alice and Bob demote each other at the same time: exactly one wins."""
    alice, bob = await sign_in("alice"), await sign_in("bob")
    # Both requests are authenticated and have loaded their target before either
    # writes, so neither sees the other's change when it starts.
    barrier = asyncio.Barrier(2)
    before_write = backend.before_write

    async def synchronized(
        session: AsyncSession, user: AuthenticatedUser, intent: WriteIntent
    ) -> PostWriteCheck | None:
        await barrier.wait()
        return await before_write(session, user, intent)

    monkeypatch.setattr(backend, "before_write", synchronized)
    results = await asyncio.gather(
        alice.patch("admin_users", 2, {"is_admin": False}),
        bob.patch("admin_users", 1, {"is_admin": False}),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert _code(loser) in {"last_admin", "conflict"}
    flags = await _flags(db)
    assert sum(1 for active, admin in flags.values() if active and admin) == 1


@pytest.mark.usefixtures("db")
async def test_locked_database_is_a_conflict_not_a_server_error(
    app: FastAPI,
    db_path: Path,
    secret_key: str,
    sign_in: Callable[[str], Awaitable[Client]],
) -> None:
    """A write that loses a lock race (SQLITE_BUSY) answers 409, never 500."""
    engine = _engine(db_path, timeout=0)  # give up on a held lock immediately
    try:
        _mount(app, engine, secret_key)
        alice = await sign_in("alice")
        holder = sqlite3.connect(db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")  # another writer holds the lock
            responses = [
                await alice.patch("teams", 1, {"name": "Platform"}),
                await alice.patch("admin_users", 2, {"is_admin": False}),
            ]
        finally:
            holder.rollback()
            holder.close()
        for response in responses:
            assert response.status_code == 409, response.text
            assert _code(response) == "conflict"
            assert "locked" not in response.text  # no driver message
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("backend")
@pytest.mark.parametrize(
    "case", [("teams", 1, {"name": "Platform"}), ("admin_users", 2, {"username": "bobby"})]
)
async def test_update_racing_a_delete_is_a_conflict(
    sign_in: Callable[[str], Awaitable[Client]],
    db: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, int, dict[str, object]],
) -> None:
    """The row is deleted after the update loaded it: 409, never 500."""
    identity, pk, body = case
    alice = await sign_in("alice")
    statement = delete(Team).where(Team.id == pk)
    if identity == "admin_users":
        statement = delete(AdminUser).where(AdminUser.id == pk)
    check_relations = write_module._check_relations

    async def delete_meanwhile(*args: Any) -> None:
        async with db.begin() as conn:  # another request deletes the row and commits
            await conn.execute(statement)
        await check_relations(*args)

    monkeypatch.setattr(write_module, "_check_relations", delete_meanwhile)
    response = await alice.patch(identity, pk, body)
    assert response.status_code == 409, response.text
    assert _code(response) == "conflict"


@pytest.mark.usefixtures("backend")
async def test_meta_marks_the_user_model_as_accounts(
    sign_in: Callable[[str], Awaitable[Client]],
) -> None:
    alice = await sign_in("alice")
    meta = (await alice.http.get("/admin/api/v1/meta")).json()
    accounts = {m["identity"]: m["account"] for m in meta["models"]}
    assert accounts == {
        "admin_users": {"protected_fields": ["is_active", "is_admin"]},
        "teams": None,
    }
    assert meta["user"]["id"] == "1"
