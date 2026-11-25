"""``Admin(sync_permissions_on_startup=True)`` (ADR-0012 §5, M19)."""

from __future__ import annotations

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
from tests.factories.contrib_models import AUTH, ContribBase
from tests.factories.models import AdminUser
from tests.integration.cli.apps import NoteAdmin


@pytest.fixture
async def db(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/startup.db")
    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.create_all)
    return engine


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
