"""The account guard on real PostgreSQL and MySQL servers (ADR-0009).

Runs when FASTSTUDIO_TEST_POSTGRES_URL / FASTSTUDIO_TEST_MYSQL_URL point at a
throwaway database whose name ends in ``_test`` (see tests/_databases.py), at
each isolation level. Each test DROPS and recreates the ``admin_users`` and
``teams`` tables. SQLite cannot exercise ``FOR UPDATE`` or snapshot isolation,
which is what these tests are about.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from faststudio import ModelUserBackend
from faststudio.api import write as write_module
from tests._databases import MYSQL_URL, POSTGRES_URL, mysql_param, postgres_param, throwaway
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

TABLES = [Base.metadata.tables["admin_users"], Base.metadata.tables["teams"]]
SNAPSHOT_LEVELS = {"REPEATABLE READ", "SERIALIZABLE"}

LEVELS = ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")


def _expected_loser(isolation: str) -> str:
    """How the losing request of two concurrent demotions is refused (always a 409).

    PostgreSQL's snapshot levels abort the loser with a serialization failure
    (``conflict``). InnoDB's ``FOR UPDATE`` is a locking read of the latest
    committed row at every level, so the loser waits, sees the other demotion
    and is refused by the rule itself (``last_admin``), as under READ COMMITTED.
    """
    server, level = isolation.split("/")
    if server == "postgres" and level in SNAPSHOT_LEVELS:
        return "conflict"
    if (server, level) == ("mysql", "SERIALIZABLE"):
        # InnoDB turns the plain reads into shared locks: the two demotions
        # deadlock and the victim is refused as a conflict.
        return "conflict"
    return "last_admin"


@pytest.fixture(
    params=[
        *(postgres_param(f"postgres/{level}") for level in LEVELS),
        *(mysql_param(f"mysql/{level}") for level in LEVELS),
    ]
)
def isolation(request: pytest.FixtureRequest) -> str:
    """``server/level``; tests read the level after the slash."""
    value: str = request.param
    return value


@pytest.fixture
async def db(isolation: str) -> AsyncIterator[AsyncEngine]:
    server, level = isolation.split("/")
    url = throwaway(POSTGRES_URL if server == "postgres" else MYSQL_URL)
    engine = create_async_engine(url, isolation_level=level)
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
async def test_rules_hold_on_servers(
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

    REPEATABLE READ / SERIALIZABLE on PostgreSQL abort the loser (40001), a conflict;
    the outcome per server and level is `_expected_loser`.
    """
    alice, bob = await sign_in("alice"), await sign_in("bob")
    synchronize_writes(backend, monkeypatch)
    loser = _one_wins(
        await asyncio.gather(
            alice.patch("admin_users", 2, {"is_admin": False}),
            bob.patch("admin_users", 1, {"is_admin": False}),
        )
    )
    assert code(loser) == _expected_loser(isolation), code(loser)
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
    isolation: str,
) -> None:
    """The row is deleted after the update loaded it: 409 (StaleDataError or 40001).

    Under MySQL SERIALIZABLE that cannot happen: the update's read share-locks
    the row, so the other request's delete waits until the update commits. The
    test then checks that instead (with a short lock-wait timeout).
    """
    identity, pk, body = case
    serializable_mysql = isolation == "mysql/SERIALIZABLE"
    blocked: list[bool] = []
    alice = await sign_in("alice")
    statement = delete(Team).where(Team.id == pk)
    if identity == "admin_users":
        statement = delete(AdminUser).where(AdminUser.id == pk)
    check_relations = write_module._check_relations

    async def delete_meanwhile(*args: Any) -> None:
        if serializable_mysql:
            from sqlalchemy import text  # noqa: PLC0415
            from sqlalchemy.exc import OperationalError  # noqa: PLC0415

            async with db.connect() as conn:
                await conn.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
                try:
                    await conn.execute(statement)
                except OperationalError as exc:  # 1205: waits for the update's lock
                    blocked.append(getattr(exc.orig, "args", (None,))[0] == 1205)
                await conn.rollback()
        else:
            async with db.begin() as conn:  # another request deletes the row and commits
                await conn.execute(statement)
        await check_relations(*args)

    monkeypatch.setattr(write_module, "_check_relations", delete_meanwhile)
    response = await alice.patch(identity, pk, body)
    if serializable_mysql:
        assert blocked == [True]  # the delete had to wait for the update
        assert response.status_code == 200, response.text
        return
    assert (response.status_code, code(response)) == (409, "conflict"), response.text
