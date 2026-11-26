"""Deliver a sliding session refresh with the response (ADR-0013).

`current_user` decides whether the session cookie is due for a refresh and
leaves the ready `Set-Cookie` value in the request scope; this wrapper adds
it to the response. A response that already sets the session cookie (login,
logout, password changes, sign out everywhere) or that is a 401 keeps its
own cookies: a refresh never resurrects a session that was just ended.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from faststudio.auth.session import SESSION_COOKIE

#: Scope key holding a one-item list for the refreshed `Set-Cookie` value.
REFRESH_KEY = "faststudio.session_refresh"
_UNAUTHORIZED = 401
_PREFIX = f"{SESSION_COOKIE}=".encode("latin-1")


def offer_refresh(scope: Scope, set_cookie: str) -> None:
    """Record a refreshed session cookie for the current response."""
    slot = scope.get(REFRESH_KEY)
    if isinstance(slot, list):
        slot[:] = [set_cookie]


class SessionRefreshMiddleware:
    """Pure ASGI wrapper that appends the refreshed cookie, if any."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Provide the slot, then add its value to the response start message."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        slot: list[str] = []
        scope[REFRESH_KEY] = slot

        async def send_with_refresh(message: Message) -> None:
            if message["type"] == "http.response.start" and slot:
                own = any(
                    name.lower() == b"set-cookie" and value.startswith(_PREFIX)
                    for name, value in message.get("headers", [])
                )
                if not own and message["status"] != _UNAUTHORIZED:
                    MutableHeaders(scope=message).append("set-cookie", slot[0])
            await send(message)

        await self.app(scope, receive, send_with_refresh)
