"""Fixtures for security integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from faststudio import Admin, ModelUserBackend, hash_password
from tests.factories.models import AdminUser, Base
from tests.integration.security._accounts import ORIGIN, PASSWORD, AuthAdminFactory, Client


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """`admin_users` with an admin, a staff member and an inactive admin (test_auth.py)."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["admin_users"]])
    maker = async_sessionmaker(engine)
    async with maker() as session:
        session.add_all(
            [
                AdminUser(username="admin", password_hash=hash_password("pw-admin"), is_admin=True),
                AdminUser(username="staff", password_hash=hash_password("pw-staff")),
                AdminUser(
                    username="gone",
                    password_hash=hash_password("pw-gone"),
                    is_admin=True,
                    is_active=False,
                ),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


@pytest.fixture
def make_auth_admin(
    app: FastAPI,
    db_engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AuthAdminFactory:
    """Build an `Admin` over `db_engine` with `ModelUserBackend(AdminUser)`."""

    def factory(**options: Any) -> Admin:
        monkeypatch.setattr("faststudio.admin._STATIC_DIR", static_dir)
        backend = options.pop("auth_backend", None) or ModelUserBackend(AdminUser)
        return Admin(app, engine=db_engine, auth_backend=backend, secret_key=secret_key, **options)

    return factory


@pytest.fixture
async def sign_in(app: FastAPI) -> AsyncIterator[Callable[[str], Awaitable[Client]]]:
    """Sign in as a seeded admin (password `PASSWORD`); one client per call."""
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
