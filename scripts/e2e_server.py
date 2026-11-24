"""Minimal FastStudio server for Playwright E2E runs (replaced by examples/basic in M12).

Serves the built SPA from src/faststudio/static through the real admin
mount, so E2E tests exercise the production CSP and security headers.
An in-memory SQLite database is seeded with one administrator whose
credentials come from FASTSTUDIO_E2E_USERNAME / FASTSTUDIO_E2E_PASSWORD
(test-only defaults; this server never runs outside the E2E suite).

Usage: python scripts/e2e_server.py [port]
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import Boolean, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from faststudio import Admin, ModelAdmin, ModelUserBackend, hash_password

E2E_USERNAME = os.environ.get("FASTSTUDIO_E2E_USERNAME", "e2e-admin")
E2E_PASSWORD = os.environ.get("FASTSTUDIO_E2E_PASSWORD", "e2e-only-password")


class _Base(DeclarativeBase):
    pass


class E2EUser(_Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserAdmin(ModelAdmin, model=E2EUser):
    list_display = ("id", "username", "is_active", "is_admin")
    exclude = ("password_hash",)
    can_create = False  # the password hash cannot be set from the admin yet


def build_app() -> FastAPI:
    """Create the E2E application with a throwaway secret and a seeded database."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                E2EUser(
                    username=E2E_USERNAME,
                    password_hash=hash_password(E2E_PASSWORD),
                    is_active=True,
                    is_admin=True,
                )
            )
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    admin = Admin(
        app,
        engine=engine,
        auth_backend=ModelUserBackend(E2EUser),
        secret_key=secrets.token_urlsafe(48),
        secure_cookies=False,  # plain-HTTP 127.0.0.1 test server
    )
    admin.register(UserAdmin)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4173
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
