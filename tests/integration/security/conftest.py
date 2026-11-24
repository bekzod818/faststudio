"""Fixtures for security integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.security._accounts import ORIGIN, PASSWORD, Client


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
