"""Authentication routes and the session dependency (ADR-0004)."""

from __future__ import annotations

import hmac
import logging
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from faststudio._spa import admin_cookie_path
from faststudio.api._context import AdminContext
from faststudio.api._paths import API_PREFIX
from faststudio.api._session_refresh import offer_refresh
from faststudio.api.errors import ApiError
from faststudio.auth.backend import AuthenticatedUser
from faststudio.auth.cookies import (
    csrf_cookie,
    expired_session_cookie,
    session_cookie,
    single_cookie,
)
from faststudio.auth.session import SESSION_COOKIE
from faststudio.schemas.contract import LoginRequest, UserMeta, UserResponse

logger = logging.getLogger("faststudio.auth")


def get_context(request: Request) -> AdminContext:
    """Return the admin context of the current sub-application."""
    context: AdminContext = request.app.state.faststudio
    return context


def cookie_path(request: Request) -> str:
    """Path for admin cookies: the admin's mount point (proxy prefix included)."""
    return admin_cookie_path(request.scope)


def ended_session_cookies(request: Request) -> list[str]:
    """`Set-Cookie` values ending a session: no session, a fresh anonymous CSRF token.

    Used by logout, sign out everywhere and every 401 for a dead session, so
    the next login works with the anonymous token.
    """
    context = get_context(request)
    path, secure = cookie_path(request), context.settings.secure_cookies
    return [
        expired_session_cookie(path=path, secure=secure),
        csrf_cookie(context.csrf.issue(session_id=None), path=path, secure=secure),
    ]


async def current_user(request: Request) -> AuthenticatedUser:
    """Require a valid session whose user may still sign in (401 otherwise)."""
    context = get_context(request)
    raw = single_cookie(request.scope, SESSION_COOKIE)
    session = context.sessions.load(raw)
    user = await context.auth_backend.get_user(request, session.user_id) if session else None
    if (
        session is None
        or user is None
        or not hmac.compare_digest(user.auth_version.encode(), session.auth_version.encode())
    ):
        # Clear the dead session and its session-bound CSRF token together.
        cookies = ended_session_cookies(request) if raw is not None else []
        raise ApiError(401, "not_authenticated", set_cookies=cookies)
    sessions = context.sessions
    if sessions.refresh_due(session):
        # Sliding idle timeout: same session id (CSRF stays bound) and issue
        # time, so the absolute expiry is unchanged; Max-Age is what is left.
        offer_refresh(
            request.scope,
            session_cookie(
                sessions.refresh(session),
                path=cookie_path(request),
                max_age=sessions.remaining(session),
                secure=context.settings.secure_cookies,
            ),
        )
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]

#: Routes that work without a session (only login).
public_router = APIRouter(prefix=API_PREFIX)
#: Every other API route: a session is required for all of them.
protected_router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])


#: Letters MySQL's utf8mb4_0900_ai_ci equates with plain ones although Unicode
#: gives them no decomposition (stroke letters, ligatures).
_FOLDED_LETTERS = str.maketrans(
    {
        "ø": "o",
        "ł": "l",
        "đ": "d",
        "ð": "d",
        "ħ": "h",
        "ŧ": "t",
        "æ": "ae",
        "œ": "oe",
    }
)
#: Mapped before NFKD, which would split them into a letter and a middle dot.
_PRE_FOLDED = str.maketrans({"ŀ": "l", "Ŀ": "L"})
#: Dropped from rate-limit keys: marks, including spacing signs such as the
#: Devanagari visarga (accents, iota subscript, combining grapheme joiner),
#: and format characters (soft hyphen, zero-width space and joiners, bidi
#: marks), which accent-insensitive collations ignore.
_DROPPED_CATEGORIES = frozenset({"Mn", "Mc", "Me", "Cf"})
#: Other characters that collation ignores: Arabic tatweel, NKo and
#: Samaritan modifiers, Mongolian nirugu, Vedic signs.
_IGNORED = frozenset("\u0640\u07fa\u0824\u0828\u180a\u1cd3\u1cf2\u1cf3")
_COMBINING_LETTER = "COMBINING LATIN SMALL LETTER "


def _fold_char(char: str) -> str:
    """One NFKD character as it counts for the rate-limit key ("" to drop it)."""
    name = unicodedata.name(char, "")
    if name.startswith(_COMBINING_LETTER):
        # The collation weighs e.g. U+0364 as the letter e ("josͤ" = "jose").
        letter = name.removeprefix(_COMBINING_LETTER).split(" ", 1)[0]
        return letter.lower() if len(letter) == 1 else ""
    if char in _IGNORED or unicodedata.category(char) in _DROPPED_CATEGORIES:
        return ""
    if unicodedata.category(char) == "Nd":
        return str(unicodedata.decimal(char))  # e.g. Arabic-Indic one (U+0661) = "1"
    return char


def rate_limit_username(username: str) -> str:
    """Normalize a username for rate-limit keys.

    Spellings that a supported database's collation may sign in as one
    account should share one bucket. This approximates MySQL's default
    utf8mb4_0900_ai_ci for the cases that matter: case and width ("Admin",
    full-width letters), accents ("José" / "jose"), invisible and ignorable
    characters (soft hyphen, zero-width space, Indic visarga), other-script
    digits, and stroke letters or ligatures ("bjørn" / "bjorn"). It is not a
    full collation table; the per-client budget caps what remains. Folding
    more only ever makes the limit stricter; PostgreSQL compares exactly.
    """
    # Marks go before casefold, which would expand some of them (the Greek
    # iota subscript into a full iota); stroke letters are mapped after it.
    decomposed = unicodedata.normalize("NFKD", username.translate(_PRE_FOLDED))
    kept = "".join(_fold_char(c) for c in decomposed)
    folded = unicodedata.normalize("NFKC", kept).casefold()
    return folded.translate(_FOLDED_LETTERS).strip()


def _user_response(user: AuthenticatedUser) -> UserResponse:
    return UserResponse(user=UserMeta(id=user.id, username=user.username))


@public_router.post("/auth/login", response_model=UserResponse)
async def login(body: LoginRequest, request: Request) -> Response:
    """Verify credentials, start a session and rotate the CSRF token."""
    context = get_context(request)
    client = request.client.host if request.client else "unknown"
    key = f"{client}|{rate_limit_username(body.username)}"
    decision = await context.client_rate_limiter.hit(client)
    if decision.allowed:
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
    path = cookie_path(request)
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
    response = Response(status_code=204)
    for cookie in ended_session_cookies(request):
        response.headers.append("set-cookie", cookie)
    return response
