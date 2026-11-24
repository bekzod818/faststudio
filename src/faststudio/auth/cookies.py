"""Build Set-Cookie headers for the session and CSRF cookies."""

from __future__ import annotations

import logging

from starlette.types import Scope

from faststudio.auth.csrf import CSRF_COOKIE
from faststudio.auth.session import SESSION_COOKIE

logger = logging.getLogger("faststudio.auth")


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


def single_cookie(scope: Scope, name: str) -> str | None:
    """Return cookie `name` if the request carries it exactly once, else None.

    Browsers send one cookie per (name, domain, path). A second `name` usually
    means a sibling (sub)domain planted one ("cookie tossing"). Frameworks
    then silently pick the first or the last; we refuse both, so a planted
    session or CSRF token never wins (threat model T3).
    """
    # Values are returned as sent: FastStudio only ever sets unquoted URL-safe
    # tokens, so RFC 2109 unquoting (as Starlette does) is deliberately skipped.
    values: list[str] = []
    for header, raw in scope.get("headers", ()):
        if header != b"cookie":
            continue
        for part in raw.decode("latin-1").split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key == name:
                values.append(value)
    if len(values) > 1:
        # Names only, never values. Also happens without an attacker when an
        # old cookie for a previous mount path is still in the browser.
        logger.warning("Refused request cookie %s sent %d times", name, len(values))
    return values[0] if len(values) == 1 else None
