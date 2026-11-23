"""Authentication routes and the session dependency (ADR-0004)."""

from __future__ import annotations

import hmac
import logging
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from faststudio._spa import ADMIN_ROOT_KEY
from faststudio.api._context import AdminContext
from faststudio.api._paths import API_PREFIX
from faststudio.api.errors import ApiError
from faststudio.auth.backend import AuthenticatedUser
from faststudio.auth.cookies import csrf_cookie, expired_session_cookie, session_cookie
from faststudio.auth.session import SESSION_COOKIE
from faststudio.schemas.contract import LoginRequest, UserMeta, UserResponse

logger = logging.getLogger("faststudio.auth")


def get_context(request: Request) -> AdminContext:
    """Return the admin context of the current sub-application."""
    context: AdminContext = request.app.state.faststudio
    return context


def _cookie_path(request: Request) -> str:
    path: str = request.scope.get(ADMIN_ROOT_KEY, request.scope.get("root_path", ""))
    return path or "/"


async def current_user(request: Request) -> AuthenticatedUser:
    """Require a valid session whose user may still sign in (401 otherwise)."""
    context = get_context(request)
    raw = request.cookies.get(SESSION_COOKIE)
    session = context.sessions.load(raw)
    user = await context.auth_backend.get_user(request, session.user_id) if session else None
    if (
        session is None
        or user is None
        or not hmac.compare_digest(user.auth_version.encode(), session.auth_version.encode())
    ):
        cookies: list[str] = []
        if raw is not None:
            # Clear the dead session and its session-bound CSRF token together,
            # so the next login works with the fresh anonymous token.
            path, secure = _cookie_path(request), context.settings.secure_cookies
            cookies = [
                expired_session_cookie(path=path, secure=secure),
                csrf_cookie(context.csrf.issue(session_id=None), path=path, secure=secure),
            ]
        raise ApiError(401, "not_authenticated", set_cookies=cookies)
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]

#: Routes that work without a session (only login).
public_router = APIRouter(prefix=API_PREFIX)
#: Every other API route: a session is required for all of them.
protected_router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])


def rate_limit_username(username: str) -> str:
    """Normalize a username for rate-limit keys (NFKC, case-folded, trimmed).

    Variants a database collation may treat as equal ("Admin", " admin",
    full-width letters) then share one bucket.
    """
    return unicodedata.normalize("NFKC", username).casefold().strip()


def _user_response(user: AuthenticatedUser) -> UserResponse:
    return UserResponse(user=UserMeta(id=user.id, username=user.username))


@public_router.post("/auth/login", response_model=UserResponse)
async def login(body: LoginRequest, request: Request) -> Response:
    """Verify credentials, start a session and rotate the CSRF token."""
    context = get_context(request)
    client = request.client.host if request.client else "unknown"
    key = f"{client}|{rate_limit_username(body.username)}"
    decision = await context.rate_limiter.hit(key)
    if not decision.allowed:
        logger.warning("Login rate limit reached for client %s", client)
        raise ApiError(429, "rate_limited", headers={"Retry-After": str(decision.retry_after)})
    user = await context.auth_backend.authenticate(request, body.username, body.password)
    if user is None:
        logger.info("Failed login attempt from client %s", client)
        raise ApiError(401, "invalid_credentials")
    await context.rate_limiter.reset(key)
    value, session = context.sessions.issue(user_id=user.id, auth_version=user.auth_version)
    secure = context.settings.secure_cookies
    path = _cookie_path(request)
    response = JSONResponse(_user_response(user).model_dump(mode="json"))
    response.headers.append(
        "set-cookie",
        session_cookie(value, path=path, max_age=context.sessions.max_age, secure=secure),
    )
    response.headers.append(
        "set-cookie",
        csrf_cookie(context.csrf.issue(session_id=session.session_id), path=path, secure=secure),
    )
    return response


@protected_router.get("/auth/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    """Return the signed-in admin."""
    return _user_response(user)


@protected_router.post("/auth/logout", status_code=204)
async def logout(request: Request) -> Response:
    """End the session (cookie cleared) and issue a fresh anonymous CSRF token."""
    context = get_context(request)
    secure = context.settings.secure_cookies
    path = _cookie_path(request)
    response = Response(status_code=204)
    response.headers.append("set-cookie", expired_session_cookie(path=path, secure=secure))
    response.headers.append(
        "set-cookie", csrf_cookie(context.csrf.issue(session_id=None), path=path, secure=secure)
    )
    return response
