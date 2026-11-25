"""DatabaseAuthBackend edge cases (M18b)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from starlette.requests import Request

from faststudio import Admin, AuthenticatedUser, BackendCapabilities, ConfigurationError
from faststudio.contrib.auth import DatabaseAuthBackend
from faststudio.contrib.auth import backend as backend_module
from tests._stubs import StubAuthBackend
from tests.factories.contrib_models import AUTH, ContribBase


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        ((object(),), {}, "must come from AuthModels"),
        ((AUTH,), {"password_validators": "strong"}, "PasswordValidator instances"),
        ((AUTH,), {"password_validators": [object()]}, "PasswordValidator instances"),
    ],
)
def test_arguments_are_validated(args: tuple[Any, ...], kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        DatabaseAuthBackend(*args, **kwargs)


def test_register_admins_must_be_callable(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    backend = StubAuthBackend()
    backend.faststudio_capabilities = BackendCapabilities(register_admins="yes")  # type: ignore[attr-defined,arg-type]
    with pytest.raises(ConfigurationError, match="register_admins must be a callable"):
        Admin(app, engine=engine, auth_backend=backend, secret_key=secret_key)


async def test_requests_need_a_mounted_admin() -> None:
    request = Request({"type": "http", "app": FastAPI()})
    with pytest.raises(ConfigurationError, match=r"mounted faststudio\.Admin"):
        await DatabaseAuthBackend(AUTH).get_user(request, "1")


async def test_non_numeric_session_ids_are_nobody() -> None:
    assert await DatabaseAuthBackend(AUTH).get_user(Request({"type": "http"}), "x1") is None


def test_superuser_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_module, "_SUPERUSER_CACHE", 2)
    backend = DatabaseAuthBackend(AUTH)
    for pk in range(5):
        row: Any = AUTH.user(id=pk, username=f"u{pk}", password_hash="h", is_superuser=False)
        row.is_active, row.session_token = True, "t"
        backend._authenticated(row)
    assert len(backend._superusers) == 2


async def test_account_manager_edges(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/accounts.db")
    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.create_all)
    backend = DatabaseAuthBackend(AUTH)
    try:
        async with AsyncSession(engine) as session:
            session.add(AUTH.user(id=1, username="ann", email="ann@example.com"))
            await session.flush()
            assert await backend.user_inputs(session, "1") == ["ann", "ann@example.com"]
            assert await backend.user_inputs(session, "2") == ()
            assert not await backend.check_password(session, "1", "any password")  # unusable
            assert not await backend.check_password(session, "x", "any password")
            await backend.set_password(session, "1", "a real passphrase")
            assert await backend.check_password(session, "1", "a real passphrase")
            with pytest.raises(LookupError):
                await backend.set_password(session, "9", "whatever it is")
            assert await backend.resolve_accounts(session, [1, 9]) == {1: frozenset()}
            user = AuthenticatedUser(id="1", username="ann", auth_version="unknown")
            assert await backend.resolve(session, user) == frozenset()  # not cached: queried
    finally:
        await engine.dispose()
