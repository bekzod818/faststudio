"""Build the isolated admin FastAPI application (ADR-0006)."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp

from faststudio._spa import AdminRootRecorder, SpaSite
from faststudio.api._context import AdminContext
from faststudio.api.auth import protected_router, public_router
from faststudio.api.errors import install_error_handlers
from faststudio.api.models import router as models_router
from faststudio.api.write import router as write_router
from faststudio.security.csrf import CsrfMiddleware
from faststudio.security.headers import SecurityHeadersMiddleware
from faststudio.security.origin import SameOriginGuard


def create_admin_app(context: AdminContext) -> FastAPI:
    """Create the admin sub-application with its API routers.

    New data routes go on `protected_router` (session required); only login
    is public. A test enumerates every API route to enforce this.
    """
    site = SpaSite(context.static_dir, context.settings)
    app = FastAPI(
        title=context.settings.title,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        redirect_slashes=False,
    )
    app.state.faststudio = context
    app.include_router(public_router)
    app.include_router(protected_router)
    app.include_router(models_router)
    app.include_router(write_router)
    app.mount(
        "/assets",
        StaticFiles(directory=context.static_dir / "assets", check_dir=False),
        name="assets",
    )
    install_error_handlers(app, site)
    return app


def wrap_admin_app(app: ASGIApp, context: AdminContext) -> ASGIApp:
    """Outer layers, outermost first: headers, admin root, same-origin guard, CSRF."""
    return SecurityHeadersMiddleware(
        AdminRootRecorder(SameOriginGuard(CsrfMiddleware(app, context)))
    )
