"""Unit tests for the security ASGI wrappers."""

from __future__ import annotations

import pytest
from starlette.types import Message, Receive, Scope, Send

from faststudio.security.headers import SecurityHeadersMiddleware
from faststudio.security.origin import SameOriginGuard, is_cross_origin


@pytest.mark.parametrize("wrapper", [SecurityHeadersMiddleware, SameOriginGuard])
async def test_non_http_scopes_pass_through(wrapper: type) -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    await wrapper(inner)({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"]


@pytest.mark.parametrize(
    ("scheme", "headers", "cross"),
    [
        ("http", [], False),
        ("http", [(b"origin", b"http://h")], True),  # no Host header to compare with
        ("http", [(b"host", b"h"), (b"origin", b"http://h")], False),
        ("http", [(b"host", b"H:80"), (b"origin", b"http://h")], False),
        ("http", [(b"host", b"h:8000"), (b"origin", b"http://h:8000")], False),
        ("http", [(b"host", b"h"), (b"origin", b"http://other")], True),
        ("http", [(b"host", b"[::1]:8000"), (b"origin", b"http://[::1]:8000")], False),
        ("http", [(b"host", b"[::1]"), (b"origin", b"http://[::1]")], False),
        ("http", [(b"host", b"[::1]"), (b"origin", b"http://[::2]")], True),
        ("https", [(b"host", b"h"), (b"origin", b"https://h:443")], False),
        ("http", [(b"host", b"h"), (b"origin", b"http://h:notaport")], True),
        ("http", [(b"host", b"h:bad"), (b"origin", b"http://h")], True),
        ("http", [(b"host", b"h"), (b"origin", b"garbage")], True),
        ("http", [(b"host", b"h"), (b"origin", b"http://")], True),
    ],
)
def test_is_cross_origin(scheme: str, headers: list[tuple[bytes, bytes]], cross: bool) -> None:
    assert is_cross_origin({"type": "http", "scheme": scheme, "headers": headers}) is cross
