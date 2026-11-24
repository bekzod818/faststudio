"""The account guard on a real PostgreSQL server (ADR-0009).

Runs only when FASTSTUDIO_TEST_POSTGRES_URL points at a throwaway database
whose name ends in ``_test``, e.g.
``postgresql+asyncpg://user@localhost:5432/faststudio_test`` (the PostgreSQL CI
job). Each test DROPS and recreates the ``admin_users`` and ``teams`` tables.
SQLite cannot exercise ``FOR UPDATE`` or snapshot isolation, which is what
these tests are about.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

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

URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
TABLES = [Base.metadata.tables["admin_users"], Base.metadata.tables["teams"]]
SNAPSHOT_LEVELS = {"REPEATABLE READ", "SERIALIZABLE"}

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL to run"),
]


@pytest.fixture(params=["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def isolation(request: pytest.FixtureRequest) -> str:
    level: str = request.param
    return level


@pytest.fixture
async def db(isolation: str) -> AsyncIterator[AsyncEngine]:
    database = make_url(URL).database or ""
    if not database.endswith("_test"):
        pytest.fail(f"Refusing to drop tables in {database!r}: use a database named *_test.")
    engine = create_async_engine(URL, isolation_level=isolation)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, tables=TABLES)
        await conn.run_sync(Base.metadata.create_all, tables=TABLES)
    async with async_sessionmaker(engine)() as session:
        session.add_all(
            [
                AdminUser(id=1, username="alice", password_hash=HASH, is_admin=True),
                AdminUser(id=2, username="bob", password_hash=HASH, is_admin=True),
                Team(id=1, name="Core"),
            ]
        )
        await session.commit()
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=TABLES)
        await engine.dispose()


@pytest.fixture
def backend(app: FastAPI, db: AsyncEngine, secret_key: str) -> ModelUserBackend:
    return mount(app, db, secret_key)


def _one_wins(results: Sequence[httpx.Response]) -> httpx.Response:
    """Exactly one request succeeded and the other got a 409 (never a 500); return the 409."""
    statuses = sorted(r.status_code for r in results)
    assert statuses in ([200, 409], [204, 409]), [r.text for r in results]
    return next(r for r in results if r.status_code == 409)


@pytest.mark.usefixtures("backend")
async def test_rules_hold_on_postgres(
    sign_in: Callable[[str], Awaitable[Client]], db: AsyncEngine
) -> None:
    alice = await sign_in("alice")
    refused = await alice.patch("admin_users", 1, {"is_admin": False})
    assert (refused.status_code, code(refused)) == (409, "self_lockout")
    assert (await alice.patch("admin_users", 2, {"is_active": False})).status_code == 200
    assert await flags(db) == {1: (True, True), 2: (False, True)}


async def test_concurrent_demotions_leave_one_admin(
    sign_in: Callable[[str], Awaitable[Client]],
    backend: ModelUserBackend,
    db: AsyncEngine,
    isolation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ COMMITTED: the loser waits, re-reads and gets last_admin.

    REPEATABLE READ / SERIALIZABLE: PostgreSQL aborts the loser (40001), a conflict.
    """
    alice, bob = await sign_in("alice"), await sign_in("bob")
    synchronize_writes(backend, monkeypatch)
    loser = _one_wins(
        await asyncio.gather(
            alice.patch("admin_users", 2, {"is_admin": False}),
            bob.patch("admin_users", 1, {"is_admin": False}),
        )
    )
    assert code(loser) == ("conflict" if isolation in SNAPSHOT_LEVELS else "last_admin")
    assert active_admins(await flags(db)) == 1


async def test_concurrent_delete_and_demotion_leave_one_admin(
    sign_in: Callable[[str], Awaitable[Client]],
    backend: ModelUserBackend,
    db: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alice deletes Bob while Bob demotes Alice: one wins, never zero admins."""
    alice, bob = await sign_in("alice"), await sign_in("bob")
    synchronize_writes(backend, monkeypatch)
    loser = _one_wins(
        await asyncio.gather(
            alice.delete("admin_users", 2),
            bob.patch("admin_users", 1, {"is_admin": False}),
        )
    )
    assert code(loser) in {"last_admin", "conflict"}
    assert active_admins(await flags(db)) == 1


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
    """The row is deleted after the update loaded it: 409 (StaleDataError or 40001)."""
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
    assert (response.status_code, code(response)) == (409, "conflict"), response.text
