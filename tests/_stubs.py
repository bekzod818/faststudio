"""Test doubles shared across test modules (import from here, not conftest)."""

from __future__ import annotations

from starlette.requests import Request

from faststudio import AuthenticatedUser


class StubAuthBackend:
    """Minimal AuthBackend used where authentication behaviour is irrelevant."""

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        return None

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        return None


class SyncAuthBackend:
    """Has the right method names but is not async: must be rejected."""

    def authenticate(self, request: Request, username: str, password: str) -> None:
        return None

    def get_user(self, request: Request, user_id: str) -> None:
        return None
