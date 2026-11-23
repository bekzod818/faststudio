"""Minimal FastStudio server for Playwright E2E runs (replaced by examples/basic in M12).

Serves the built SPA from src/faststudio/static through the real admin
mount, so E2E tests exercise the production CSP and security headers.

Usage: python scripts/e2e_server.py [port]
"""

from __future__ import annotations

import secrets
import sys

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request

from faststudio import Admin, AuthenticatedUser


class _NoLoginBackend:
    """Rejects every login; enough for serving the SPA shell."""

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        return None

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        return None


def build_app() -> FastAPI:
    """Create the E2E application with a throwaway secret and in-memory database."""
    app = FastAPI()
    Admin(
        app,
        engine=create_async_engine("sqlite+aiosqlite://"),
        auth_backend=_NoLoginBackend(),
        secret_key=secrets.token_urlsafe(48),
        secure_cookies=False,  # plain-HTTP 127.0.0.1 test server
    )
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4173
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
