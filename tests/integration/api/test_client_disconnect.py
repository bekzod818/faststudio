"""A browser that leaves while sending a write body (v0.2 item 5).

Uvicorn used to log "Exception in ASGI application" with a ClientDisconnect
traceback, and the admin logged an unhandled 500: the write endpoints read
the body themselves. Nothing is wrong when a client leaves, so only a debug
line remains.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.types import Message

from tests.factories.models import Team

BASE = "/admin/api/v1/models"


async def _send_without_body(
    app: FastAPI, api: httpx.AsyncClient, method: str, path: str
) -> list[Message]:
    """Run the request in ASGI directly; the client disconnects before any body."""
    cookie = "; ".join(f"{c.name}={c.value}" for c in api.cookies.jar)
    token = api.cookies["faststudio_csrftoken"]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", b"64"),
            (b"origin", b"https://testserver"),
            (b"x-faststudio-csrf", token.encode()),
            (b"cookie", cookie.encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 443),
    }

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)  # must not raise to the server
    return sent


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", f"{BASE}/teams/items/1"),
        ("POST", f"{BASE}/teams/items"),
    ],
)
async def test_a_client_leaving_mid_body_is_not_an_error(  # noqa: PLR0917 - fixtures
    app: FastAPI,
    api: httpx.AsyncClient,
    db: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
) -> None:
    async with AsyncSession(db) as session:
        before = list(await session.scalars(select(Team.name).order_by(Team.id)))
    with caplog.at_level(logging.DEBUG, logger="faststudio"):
        await _send_without_body(app, api, method, path)
    problems = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert problems == [], [r.getMessage() for r in problems]
    assert any("disconnected" in r.getMessage() for r in caplog.records)
    async with AsyncSession(db) as session:
        assert list(await session.scalars(select(Team.name).order_by(Team.id))) == before
