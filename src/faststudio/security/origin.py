"""Same-origin guard for the admin JSON API (threat model T3)."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from faststudio._spa import ADMIN_ROOT_KEY
from faststudio.api.errors import error_response

# `none` = direct navigation / non-browser client; anything else is another site.
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize(scheme: str, netloc: str) -> str | None:
    """`scheme://host[:port]`, lower-cased, without the default port; None if malformed."""
    try:
        parts = urlsplit(f"//{netloc}")
        hostname, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not hostname:
        return None
    scheme = scheme.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def _request_origin(scope: Scope, headers: Headers) -> str | None:
    host = headers.get("host")
    return _normalize(scope.get("scheme", "http"), host) if host else None


def _origin(value: str) -> str | None:
    scheme, sep, netloc = value.partition("://")
    return _normalize(scheme, netloc) if sep else None


def is_cross_origin(scope: Scope) -> bool:
    """Return True if a browser marked the request as coming from another origin.

    Uses `Sec-Fetch-Site` when present (modern browsers), otherwise compares
    `Origin` with the request's own scheme and host. Requests carrying neither
    header (curl, server-to-server) are not browser cross-site requests.
    """
    headers = Headers(scope=scope)
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site.lower() not in _ALLOWED_FETCH_SITES
    origin = headers.get("origin")
    if origin is None:
        return False
    expected = _request_origin(scope, headers)
    return expected is None or _origin(origin) != expected


class SameOriginGuard:
    """Reject cross-origin browser requests to `/api/*`, for every method.

    CSRF tokens (M6) protect unsafe methods; this guard also protects reads
    when the host application installs a permissive, credentialed CORS policy.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the admin application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Return 403 `csrf_failed` for cross-origin API requests."""
        if scope["type"] == "http" and self._is_api(scope) and is_cross_origin(scope):
            response = error_response(403, "csrf_failed", "Cross-origin request rejected.")
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _is_api(scope: Scope) -> bool:
        root: str = scope.get(ADMIN_ROOT_KEY, scope.get("root_path", ""))
        path: str = scope["path"]
        relative = path[len(root) :] if path.startswith(root) else path
        return relative == "/api" or relative.startswith("/api/")
