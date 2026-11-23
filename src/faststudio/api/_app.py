"""Build the isolated admin FastAPI application (ADR-0006)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp

from faststudio._spa import AdminRootRecorder, SpaSite
from faststudio.api.errors import install_error_handlers
from faststudio.auth.backend import AuthBackend
from faststudio.config import Settings
from faststudio.registry import Registry
from faststudio.security.headers import SecurityHeadersMiddleware
from faststudio.security.origin import SameOriginGuard


@dataclass(frozen=True, slots=True)
class AdminContext:
    """Everything request handling needs; routers (M6+) receive this object."""

    settings: Settings
    registry: Registry
    session_maker: async_sessionmaker[AsyncSession]
    auth_backend: AuthBackend
    static_dir: Path


def create_admin_app(context: AdminContext) -> FastAPI:
    """Create the admin sub-application; routers are added with `include_router`."""
    site = SpaSite(context.static_dir, context.settings)
    app = FastAPI(
        title=context.settings.title,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        redirect_slashes=False,
    )
    app.state.faststudio = context
    app.mount(
        "/assets",
        StaticFiles(directory=context.static_dir / "assets", check_dir=False),
        name="assets",
    )
    install_error_handlers(app, site)
    return app


def wrap_admin_app(app: ASGIApp) -> ASGIApp:
    """Outer layers, outermost first: security headers, admin root, same-origin guard."""
    return SecurityHeadersMiddleware(AdminRootRecorder(SameOriginGuard(app)))
