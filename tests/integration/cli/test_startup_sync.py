"""``Admin(sync_permissions_on_startup=True)`` (ADR-0012 §5, M19)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from faststudio import Admin, ConfigurationError, ModelUserBackend
from faststudio.api._permission_sync import plan_sync
from faststudio.api._startup_sync import StartupPermissionSync
from faststudio.contrib.auth import DatabaseAuthBackend
from tests._databases import MYSQL_URL, mysql_param, throwaway
from tests.factories.contrib_models import AUTH, ContribBase
from tests.factories.models import AdminUser
from tests.integration.cli.apps import NoteAdmin


@pytest.fixture(params=["sqlite", mysql_param("mysql")])
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if request.param == "mysql":
        engine = create_async_engine(throwaway(MYSQL_URL))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/startup.db")
    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.drop_all)
        await conn.run_sync(ContribBase.metadata.create_all)
    try:
        yield engine
    finally:  # also when a test fails before its own dispose()
        await engine.dispose()


async def _codenames(db: AsyncEngine) -> set[str]:
    async with AsyncSession(db) as session:
        return set(await session.scalars(select(AUTH.permission.codename)))


async def test_the_first_admin_request_syncs_once(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    admin = Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    admin.register(NoteAdmin)
    assert await _codenames(db) == set()  # nothing at construction
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        await http.get("/admin/api/v1/auth/me")
        assert {"notes.view", "notes.publish", "faststudio_user.edit"} <= await _codenames(db)
        async with db.begin() as conn:  # a stale codename: never pruned
            await conn.execute(AUTH.permission.__table__.insert().values(codename="gone.view"))  # type: ignore[attr-defined]
        await http.get("/admin/api/v1/auth/me")
    assert "gone.view" in await _codenames(db)
    await db.dispose()


async def test_a_failed_sync_is_logged_and_retried(
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    real = plan_sync
    calls = {"n": 0}

    async def flaky(*args: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "database is down"
            raise ConnectionError(msg)
        return await real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr("faststudio.api._startup_sync.plan_sync", flaky)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        with caplog.at_level("WARNING", logger="faststudio"):
            first = await http.get("/admin/api/v1/auth/me")
        assert first.status_code == 401  # served anyway
        assert "Permission sync failed (ConnectionError); retrying later." in caplog.text
        assert await _codenames(db) == set()
        await http.get("/admin/api/v1/auth/me")  # within the retry interval: not retried
        assert calls["n"] == 1
        monkeypatch.setattr("faststudio.api._startup_sync.RETRY_INTERVAL", 0.0)
        monkeypatch.setattr("time.monotonic", lambda: 10**9)  # well past the interval
        await http.get("/admin/api/v1/auth/me")
    assert "faststudio_user.view" in await _codenames(db)
    await db.dispose()


@pytest.mark.parametrize(
    ("backend", "value", "match"),
    [
        ("model", True, "needs an auth backend with a permission schema"),
        ("contrib", "yes", "must be a bool"),
    ],
)
def test_startup_sync_is_validated(  # noqa: PLR0917 - fixtures and parameters
    app: FastAPI, engine: AsyncEngine, secret_key: str, backend: str, value: object, match: str
) -> None:
    auth = ModelUserBackend(AdminUser) if backend == "model" else DatabaseAuthBackend(AUTH)
    with pytest.raises(ConfigurationError, match=match):
        Admin(
            app,
            engine=engine,
            auth_backend=auth,
            secret_key=secret_key,
            sync_permissions_on_startup=value,  # type: ignore[arg-type]
        )


async def test_a_finished_sync_is_not_repeated() -> None:
    wrapper: Any = StartupPermissionSync(
        lambda *a: None,  # type: ignore[arg-type]
        rules=None,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        session_maker=None,  # type: ignore[arg-type]
    )
    wrapper.done = True
    await wrapper._sync()  # returns before touching the database


class _DeadlockError(Exception):
    """A driver error with MySQL's deadlock number (1213)."""

    def __init__(self) -> None:
        super().__init__(1213, "Deadlock found when trying to get lock")


@pytest.mark.parametrize(("conflicts", "logged"), [(1, False), (4, False), (5, True)])
async def test_a_lost_race_is_retried_after_a_short_backoff(  # noqa: PLR0917 - fixtures and parameters
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    conflicts: int,
    logged: bool,
) -> None:
    """A deadlock victim (another process won): retried a few times, not logged."""
    from sqlalchemy.exc import OperationalError  # noqa: PLC0415

    Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    real = plan_sync
    calls = {"n": 0}

    async def contended(*args: object) -> object:
        calls["n"] += 1
        if calls["n"] <= conflicts:
            raise OperationalError("INSERT ...", {}, _DeadlockError())
        return await real(*args)  # type: ignore[arg-type]

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("faststudio.api._startup_sync.plan_sync", contended)
    monkeypatch.setattr("faststudio.api._startup_sync._sleep", no_wait)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        with caplog.at_level("WARNING", logger="faststudio"):
            assert (await http.get("/admin/api/v1/auth/me")).status_code == 401
    if logged:  # still contended after every attempt: the usual retry later
        assert "Permission sync failed (OperationalError); retrying later." in caplog.text
        assert calls["n"] == 5
        assert await _codenames(db) == set()
    else:
        assert caplog.text == ""
        assert calls["n"] == conflicts + 1
        assert "faststudio_user.view" in await _codenames(db)
    await db.dispose()


async def test_other_database_errors_are_not_retried_at_once(
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sqlalchemy.exc import ProgrammingError  # noqa: PLC0415

    Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    calls = {"n": 0}

    async def missing_table(*_args: object) -> object:
        calls["n"] += 1
        raise ProgrammingError("SELECT ...", {}, Exception("no such table"))

    monkeypatch.setattr("faststudio.api._startup_sync.plan_sync", missing_table)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        with caplog.at_level("WARNING", logger="faststudio"):
            await http.get("/admin/api/v1/auth/me")
    assert calls["n"] == 1
    assert "Permission sync failed (ProgrammingError); retrying later." in caplog.text
    await db.dispose()


class _LockWaitTimeoutError(Exception):
    """MySQL's lock-wait timeout (1205): it already waited."""

    def __init__(self) -> None:
        super().__init__(1205, "Lock wait timeout exceeded")


async def test_lock_wait_timeouts_are_not_retried_at_once(
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retrying a timeout would hold every admin request for several timeouts."""
    from sqlalchemy.exc import OperationalError  # noqa: PLC0415

    Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    calls = {"n": 0}

    async def waited(*_args: object) -> object:
        calls["n"] += 1
        raise OperationalError("INSERT ...", {}, _LockWaitTimeoutError())

    monkeypatch.setattr("faststudio.api._startup_sync.plan_sync", waited)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        with caplog.at_level("WARNING", logger="faststudio"):
            await http.get("/admin/api/v1/auth/me")
    assert calls["n"] == 1
    assert "Permission sync failed (OperationalError); retrying later." in caplog.text
    await db.dispose()


async def test_retries_stop_within_the_time_budget(
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError  # noqa: PLC0415

    Admin(
        app,
        engine=db,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=secret_key,
        sync_permissions_on_startup=True,
    )
    calls = {"n": 0}
    clock = {"now": 1000.0}

    async def deadlocked(*_args: object) -> object:
        calls["n"] += 1
        raise OperationalError("INSERT ...", {}, _DeadlockError())

    async def slow_sleep(seconds: float) -> None:
        clock["now"] += seconds + 1.0  # each wait takes a second longer than planned

    monkeypatch.setattr("faststudio.api._startup_sync.plan_sync", deadlocked)
    monkeypatch.setattr("faststudio.api._startup_sync._sleep", slow_sleep)
    monkeypatch.setattr("faststudio.api._startup_sync._monotonic", lambda: clock["now"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://t") as http:
        await http.get("/admin/api/v1/auth/me")
    assert calls["n"] == 2  # the third attempt would start after the 2 s budget
    await db.dispose()
