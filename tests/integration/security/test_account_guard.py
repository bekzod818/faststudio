"""Admins cannot lock themselves out or remove the last active admin (ADR-0009)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from faststudio import ModelUserBackend
from faststudio.api import write as write_module
from tests.factories.models import AdminUser, Base, Team
from tests.integration.security._accounts import (
    HASH,
    Client,
    active_admins,
    code,
    flags,
    mount,
    synchronize_writes,
)


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


@pytest.fixture
def backend(app: FastAPI, db: AsyncEngine, secret_key: str) -> ModelUserBackend:
    return mount(app, db, secret_key)


# ------------------------------------------------------------------ self-lockout


@pytest.mark.usefixtures("backend")
@pytest.mark.parametrize("field", ["is_admin", "is_active"])
async def test_admin_cannot_remove_own_access(
    sign_in: Callable[[str], Awaitable[Client]], db: AsyncEngine, field: str
) -> None:
    alice = await sign_in("alice")
    response = await alice.patch("admin_users", 1, {field: False, "username": "renamed"})
    assert response.status_code == 409
    assert code(response) == "self_lockout"
    assert "own" in response.json()["error"]["message"]
    assert (await flags(db))[1] == (True, True)
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
    assert code(response) == "self_lockout"
    assert 1 in await flags(db)
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
    assert await flags(db) == {1: (True, True), 3: (False, True)}


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
    synchronize_writes(backend, monkeypatch)
    results = await asyncio.gather(
        alice.patch("admin_users", 2, {"is_admin": False}),
        bob.patch("admin_users", 1, {"is_admin": False}),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert code(loser) in {"last_admin", "conflict"}
    assert active_admins(await flags(db)) == 1


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
        mount(app, engine, secret_key)
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
            assert code(response) == "conflict"
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
    assert code(response) == "conflict"


@pytest.mark.usefixtures("backend")
async def test_meta_marks_the_user_model_as_accounts(
    sign_in: Callable[[str], Awaitable[Client]],
) -> None:
    alice = await sign_in("alice")
    meta = (await alice.http.get("/admin/api/v1/meta")).json()
    accounts = {m["identity"]: m["account"] for m in meta["models"]}
    assert accounts == {
        "admin_users": {"protected_fields": ["is_active", "is_admin"], "admin_flag": "is_admin"},
        "teams": None,
    }
    assert meta["user"]["id"] == "1"
