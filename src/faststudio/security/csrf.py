"""CSRF enforcement and token issuance for the admin (threat model T3)."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from faststudio._spa import ADMIN_ROOT_KEY, admin_cookie_path
from faststudio.api._paths import LOGIN_PATH
from faststudio.api.errors import error_response
from faststudio.auth.cookies import csrf_cookie, expired_session_cookie, single_cookie
from faststudio.auth.csrf import CSRF_COOKIE, CSRF_HEADER
from faststudio.auth.session import SESSION_COOKIE

if TYPE_CHECKING:
    from faststudio.api._context import AdminContext

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _relative(scope: Scope) -> str:
    root: str = scope.get(ADMIN_ROOT_KEY, scope.get("root_path", ""))
    path: str = scope["path"]
    return path[len(root) :] if path.startswith(root) else path


class CsrfMiddleware:
    """Validate unsafe API requests and keep a valid CSRF cookie in the browser.

    Unsafe methods under `/api/` need header `X-FastStudio-CSRF` equal to
    cookie `faststudio_csrftoken` (constant-time) and a token valid for the
    current session. Anonymous tokens are accepted only without a session,
    or on the login route. Any response gets a fresh token cookie when the
    current one is missing or invalid; routes that rotate it themselves win.

    An unsafe request carrying a session cookie that is no longer valid
    (expired, idle, tampered) gets `401 not_authenticated` with the cookie
    cleared, before the token check: its token was bound to that session, so
    it would otherwise always be `403 csrf_failed`, and the UI could not
    tell an ended session from a forged request. Nothing runs either way.
    """

    def __init__(self, app: ASGIApp, context: AdminContext) -> None:
        """Wrap the admin app."""
        self.app = app
        self.context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Enforce, then forward with token issuance."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        raw_session = single_cookie(scope, SESSION_COOKIE)
        session = self.context.sessions.load(raw_session)
        session_id = session.session_id if session else None
        cookie_token = single_cookie(scope, CSRF_COOKIE)
        cookie_ok = cookie_token is not None and self.context.csrf.verify(
            cookie_token, session_id=session_id
        )
        relative = _relative(scope)
        # Never put a per-user cookie on immutable, publicly cacheable asset responses.
        refresh = not cookie_ok and not relative.startswith("/assets/")
        send = self._issuing_send(scope, send, session_id, refresh=refresh)
        is_api = relative == "/api" or relative.startswith("/api/")
        if is_api and scope["method"] in UNSAFE_METHODS:
            # A duplicated (tossed) session cookie reads as absent here, so it
            # still meets the token check below (403), as before.
            if raw_session and session is None and relative != LOGIN_PATH:
                response = error_response(401, "not_authenticated")
                response.headers.append(
                    "set-cookie",
                    expired_session_cookie(
                        path=admin_cookie_path(scope), secure=self.context.settings.secure_cookies
                    ),
                )
                await response(scope, receive, send)  # plus a fresh anonymous token
                return
            header = connection.headers.get(CSRF_HEADER)
            if not self._valid(header, cookie_token, session_id, login=relative == LOGIN_PATH):
                response = error_response(403, "csrf_failed")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _valid(
        self, header: str | None, cookie: str | None, session_id: str | None, *, login: bool
    ) -> bool:
        if not header or not cookie:
            return False
        if not hmac.compare_digest(header.encode(), cookie.encode()):
            return False
        csrf = self.context.csrf
        return csrf.verify(header, session_id=session_id) or (
            login and csrf.verify(header, session_id=None)
        )

    def _issuing_send(
        self, scope: Scope, send: Send, session_id: str | None, *, refresh: bool
    ) -> Send:
        if not refresh:
            return send
        settings = self.context.settings
        path = admin_cookie_path(scope)
        prefix = f"{CSRF_COOKIE}=".encode()

        async def issuing_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                already = any(v.encode().startswith(prefix) for v in headers.getlist("set-cookie"))
                if not already:
                    token = self.context.csrf.issue(session_id=session_id)
                    headers.append(
                        "set-cookie",
                        csrf_cookie(token, path=path, secure=settings.secure_cookies),
                    )
            await send(message)

        return issuing_send
