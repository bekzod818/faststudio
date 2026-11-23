"""Shared pytest fixtures."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
def _no_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never pick up a developer's real FASTSTUDIO_SECRET_KEY."""
    monkeypatch.delenv("FASTSTUDIO_SECRET_KEY", raising=False)
