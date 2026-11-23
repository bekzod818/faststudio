"""Security headers for every admin response (threat model T6)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
STATIC_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
HSTS = "max-age=63072000"
IMMUTABLE = "public, max-age=31536000, immutable"
# Full, partial and revalidated asset responses keep the immutable policy (RFC 9111 4.3.4).
_CACHEABLE_STATUSES = frozenset({200, 206, 304})


class SecurityHeadersMiddleware:
    """Pure ASGI wrapper around the admin app.

    It sits *outside* the admin app so it also covers responses produced by
    Starlette's own error middleware (500s) and the trailing-slash redirect.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap `app`."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Add headers to the response start message."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # At the mount, root_path is the browser-visible admin root (proxy prefix + base_url).
        assets_prefix = f"{scope.get('root_path', '')}/assets/"
        is_asset = scope["path"].startswith(assets_prefix)
        https = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in STATIC_HEADERS.items():
                    headers[name] = value
                if https:
                    headers["Strict-Transport-Security"] = HSTS
                cacheable = is_asset and message["status"] in _CACHEABLE_STATUSES
                headers["Cache-Control"] = IMMUTABLE if cacheable else "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
