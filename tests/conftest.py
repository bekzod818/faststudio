"""Shared pytest fixtures."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests._leaks import aiosqlite_workers, assert_no_leaked_workers, check_identifiable
from tests._stubs import StubAuthBackend


@pytest.fixture
def secret_key() -> str:
    return secrets.token_urlsafe(48)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def auth_backend() -> StubAuthBackend:
    return StubAuthBackend()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite://")
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
def _no_built_spa(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never depend on a locally built SPA; integration tests provide their own."""
    monkeypatch.setattr(
        "faststudio.admin._STATIC_DIR", tmp_path_factory.mktemp("no-spa") / "static"
    )


@pytest.fixture(autouse=True)
def _no_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never pick up a developer's real FASTSTUDIO_SECRET_KEY."""
    monkeypatch.delenv("FASTSTUDIO_SECRET_KEY", raising=False)


@pytest.fixture(scope="session", autouse=True)
def _leak_guard_can_see_aiosqlite() -> None:
    """The leak guard below must not pass silently if it cannot see the threads."""
    check_identifiable()


@pytest.fixture(autouse=True)
def _no_leaked_db_connections() -> Iterator[None]:
    """Fail the test that leaves an aiosqlite connection open (see tests/_leaks.py)."""
    before = aiosqlite_workers()
    yield
    assert_no_leaked_workers(before)
