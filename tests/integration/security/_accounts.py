"""Shared helpers for the account-guard tests (ADR-0009); not a test module."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from faststudio import Admin, AuthenticatedUser, ModelAdmin, ModelUserBackend, hash_password
from faststudio.auth._guard import PostWriteCheck, WriteIntent
from tests.factories.models import AdminUser, Team

ORIGIN = "https://testserver"
BASE = "/admin/api/v1/models"
PASSWORD = "a long test passphrase"
HASH = hash_password(PASSWORD)


class AdminUserAdmin(ModelAdmin, model=AdminUser):
    list_display = ("id", "username", "is_active", "is_admin")
    exclude = ("password_hash",)


class TeamAdmin(ModelAdmin, model=Team):
    list_display = ("id", "name")


def mount(app: FastAPI, engine: AsyncEngine, secret_key: str) -> ModelUserBackend:
    """Mount an admin that registers the user model (guarded) and teams."""
    backend = ModelUserBackend(AdminUser)
    admin = Admin(app, engine=engine, auth_backend=backend, secret_key=secret_key)
    admin.register(AdminUserAdmin)
    admin.register(TeamAdmin)
    return backend


class Client:
    """A signed-in admin: an HTTPS client plus CSRF-aware write helpers."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def patch(self, identity: str, pk: int, body: object) -> httpx.Response:
        url = f"{BASE}/{identity}/items/{pk}"
        return await self.http.patch(url, json=body, headers=self._headers())

    async def delete(self, identity: str, pk: int) -> httpx.Response:
        return await self.http.delete(f"{BASE}/{identity}/items/{pk}", headers=self._headers())

    async def me(self) -> int:
        return (await self.http.get("/admin/api/v1/auth/me")).status_code


async def flags(db: AsyncEngine) -> dict[int, tuple[bool, bool]]:
    """Return `{id: (is_active, is_admin)}` for every admin_users row."""
    async with AsyncSession(db) as session:
        rows = (await session.execute(AdminUser.__table__.select())).all()
    return {row.id: (row.is_active, row.is_admin) for row in rows}


def active_admins(rows: dict[int, tuple[bool, bool]]) -> int:
    return sum(1 for active, admin in rows.values() if active and admin)


def code(response: httpx.Response) -> str:
    value: str = response.json()["error"]["code"]
    return value


def synchronize_writes(
    backend: ModelUserBackend, monkeypatch: pytest.MonkeyPatch, parties: int = 2
) -> None:
    """Hold guarded writes until `parties` requests reach the guard.

    Every request is then authenticated and has loaded its target (and, under
    snapshot isolation, taken its snapshot) before any of them writes.
    """
    barrier = asyncio.Barrier(parties)
    before_write = backend.before_write

    async def synchronized(
        session: AsyncSession, user: AuthenticatedUser, intent: WriteIntent
    ) -> PostWriteCheck | None:
        await barrier.wait()
        return await before_write(session, user, intent)

    monkeypatch.setattr(backend, "before_write", synchronized)
