"""Build Set-Cookie headers for the session and CSRF cookies."""

from __future__ import annotations

from faststudio.auth.csrf import CSRF_COOKIE
from faststudio.auth.session import SESSION_COOKIE


def cookie_header(
    name: str, value: str, *, path: str, max_age: int | None, http_only: bool, secure: bool
) -> str:
    """Return a `Set-Cookie` value. Values are URL-safe tokens, so no quoting is needed."""
    parts = [f"{name}={value}", f"Path={path or '/'}", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    if http_only:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def session_cookie(value: str, *, path: str, max_age: int, secure: bool) -> str:
    """Session cookie: HttpOnly, never readable by scripts."""
    return cookie_header(
        SESSION_COOKIE, value, path=path, max_age=max_age, http_only=True, secure=secure
    )


def expired_session_cookie(*, path: str, secure: bool) -> str:
    """Delete the session cookie."""
    return cookie_header(SESSION_COOKIE, "", path=path, max_age=0, http_only=True, secure=secure)


def csrf_cookie(token: str, *, path: str, secure: bool) -> str:
    """CSRF cookie: readable by the SPA (double submit), session-scoped in the browser."""
    return cookie_header(
        CSRF_COOKIE, token, path=path, max_age=None, http_only=False, secure=secure
    )
