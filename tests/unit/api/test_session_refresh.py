"""The sliding-refresh ASGI layer (ADR-0013)."""

from __future__ import annotations

from starlette.types import Message, Receive, Scope, Send

from faststudio.api._session_refresh import REFRESH_KEY, SessionRefreshMiddleware, offer_refresh


async def test_non_http_scopes_pass_through() -> None:
    seen: list[Scope] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del receive, send
        seen.append(scope)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        del message

    scope: Scope = {"type": "lifespan"}
    await SessionRefreshMiddleware(app)(scope, receive, send)
    assert seen == [scope]
    assert REFRESH_KEY not in scope


def test_offering_without_the_layer_does_nothing() -> None:
    scope: Scope = {"type": "http"}
    offer_refresh(scope, "faststudio_session=x")
    assert scope == {"type": "http"}
