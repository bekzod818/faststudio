"""ModelUserBackend: admins from the host's own user model (ADR-0004)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from faststudio import AuthBackend, ConfigurationError, ModelUserBackend, hash_password
from tests.factories.models import (
    AdminUser,
    Base,
    CompositeLogin,
    DatedLogin,
    IndexedAdmin,
    LegacyAdmin,
    NotMapped,
    Operator,
    Team,
    TenantAdmin,
)


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables[name] for name in ("admin_users", "operators", "legacy_admins")
            ],
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        session.add_all(
            [
                AdminUser(username="admin", password_hash=hash_password("pw-admin"), is_admin=True),
                AdminUser(
                    username="inactive",
                    password_hash=hash_password("pw"),
                    is_admin=True,
                    is_active=False,
                ),
                AdminUser(username="staff", password_hash=hash_password("pw"), is_admin=False),
                AdminUser(username="broken", password_hash="not-a-hash", is_admin=True),
                AdminUser(
                    username="legacy",
                    password_hash="$2b$12$abcdefghijklmnopqrstuuJ6sTqv3Hk0g4yGQ0B5UqgwkXnG0hYyK",
                    is_admin=True,
                ),
                Operator(login="op", secret=hash_password("pw-op"), enabled=True),
            ]
        )
        await session.commit()
    yield session_maker
    await engine.dispose()


def _request(maker: async_sessionmaker[AsyncSession]) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(faststudio=SimpleNamespace(session_maker=maker)))
    return Request({"type": "http", "headers": [], "app": app})


async def test_authenticates_active_admin(maker: async_sessionmaker[AsyncSession]) -> None:
    user = await ModelUserBackend(AdminUser).authenticate(_request(maker), "admin", "pw-admin")
    assert user is not None
    assert (user.id, user.username) == ("1", "admin")
    assert user.auth_version


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "wrong"),
        ("nobody", "pw"),
        ("inactive", "pw"),
        ("staff", "pw"),
        ("broken", "pw"),
        ("ADMIN", "pw-admin"),
        (" admin", "pw-admin"),
    ],
)
async def test_rejects_without_saying_why(
    maker: async_sessionmaker[AsyncSession], username: str, password: str
) -> None:
    assert (
        await ModelUserBackend(AdminUser).authenticate(_request(maker), username, password) is None
    )


@pytest.mark.parametrize("username", ["nobody", "broken", "legacy"])
async def test_unknown_or_unusable_hash_still_runs_a_verification(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch, username: str
) -> None:
    """No hash, legacy bcrypt or garbage must take as long as a wrong password."""
    calls: list[str] = []

    def spy(password: str) -> bool:
        calls.append(password)
        return False

    monkeypatch.setattr("faststudio.auth.model_backend.dummy_verify", spy)
    backend = ModelUserBackend(AdminUser)
    assert await backend.authenticate(_request(maker), username, "pw") is None
    assert calls == ["pw"]


async def test_inactive_and_non_admin_rows_still_verify_password(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def spy(stored: str, password: str) -> bool:
        calls.append(password)
        return True

    monkeypatch.setattr("faststudio.auth.model_backend.verify_password", spy)
    backend = ModelUserBackend(AdminUser)
    assert await backend.authenticate(_request(maker), "inactive", "pw") is None
    assert await backend.authenticate(_request(maker), "staff", "pw") is None
    assert calls == ["pw", "pw"]  # same work as a successful login


async def test_get_user_and_auth_version(maker: async_sessionmaker[AsyncSession]) -> None:
    backend = ModelUserBackend(AdminUser)
    request = _request(maker)
    logged_in = await backend.authenticate(request, "admin", "pw-admin")
    assert logged_in is not None
    assert await backend.get_user(request, "1") == logged_in
    async with maker() as session:
        user = await session.get(AdminUser, 1)
        assert user is not None
        user.password_hash = hash_password("new-password")
        await session.commit()
    changed = await backend.get_user(request, "1")
    assert changed is not None
    assert changed.auth_version != logged_in.auth_version


@pytest.mark.parametrize("user_id", ["2", "3", "999", "abc", "", "1.0", "-1"])
async def test_get_user_rejects_missing_inactive_or_malformed_ids(
    maker: async_sessionmaker[AsyncSession], user_id: str
) -> None:
    assert await ModelUserBackend(AdminUser).get_user(_request(maker), user_id) is None


async def test_custom_columns_uuid_pk_and_no_admin_flag(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    backend = ModelUserBackend(
        Operator,
        username_field="login",
        password_field="secret",
        is_active_field="enabled",
        is_admin_field=None,
    )
    request = _request(maker)
    user = await backend.authenticate(request, "op", "pw-op")
    assert user is not None
    assert await backend.get_user(request, user.id) == user
    assert await backend.get_user(request, "not-a-uuid") is None


def test_satisfies_protocol() -> None:
    assert isinstance(ModelUserBackend(AdminUser), AuthBackend)


@pytest.mark.parametrize(
    ("model", "kwargs", "match"),
    [
        (NotMapped, {}, "mapped SQLAlchemy class"),
        (AdminUser, {"username_field": "email"}, "username_field"),
        (AdminUser, {"password_field": "pw"}, "password_field"),
        (AdminUser, {"is_active_field": "active"}, "is_active_field"),
        (AdminUser, {"is_admin_field": "superuser"}, "is_admin_field"),
        (AdminUser, {"is_admin_field": "username"}, "boolean"),
        (AdminUser, {"username_field": "is_admin"}, "string"),
        (Team, {"username_field": "name", "password_field": "name"}, "differ"),
        (
            CompositeLogin,
            {
                "username_field": "login",
                "password_field": "pw",
                "is_active_field": None,
                "is_admin_field": None,
            },
            "single-column primary key",
        ),
        (
            DatedLogin,
            {
                "username_field": "login",
                "password_field": "pw",
                "is_active_field": None,
                "is_admin_field": None,
            },
            "integer, UUID or string",
        ),
    ],
)
def test_configuration_is_validated(model: type[Any], kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        ModelUserBackend(model, **kwargs)


def test_request_without_admin_context_fails_loudly() -> None:
    backend = ModelUserBackend(AdminUser)
    request = Request(
        {"type": "http", "headers": [], "app": SimpleNamespace(state=SimpleNamespace())}
    )
    with pytest.raises(ConfigurationError, match="mounted"):
        backend._session_maker(request)


async def test_null_password_column_runs_dummy_verification(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def spy(password: str) -> bool:
        calls.append(password)
        return False

    monkeypatch.setattr("faststudio.auth.model_backend.dummy_verify", spy)
    async with maker() as session:
        session.add(LegacyAdmin(username="sso-only", password_hash=None, is_admin=True))
        await session.commit()
    backend = ModelUserBackend(LegacyAdmin)
    assert await backend.authenticate(_request(maker), "sso-only", "pw") is None
    assert calls == ["pw"]


async def test_duplicate_usernames_are_refused(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as session:
        session.add_all(
            [
                LegacyAdmin(username="dup", password_hash=hash_password("pw"), is_admin=True),
                LegacyAdmin(username="dup", password_hash=hash_password("pw"), is_admin=True),
            ]
        )
        await session.commit()
    assert await ModelUserBackend(LegacyAdmin).authenticate(_request(maker), "dup", "pw") is None


@pytest.mark.parametrize("model", [LegacyAdmin, TenantAdmin])
def test_non_unique_username_column_logs_warning(
    caplog: pytest.LogCaptureFixture, model: type[object]
) -> None:
    with caplog.at_level("WARNING", logger="faststudio.auth"):
        ModelUserBackend(model)
    assert any("not declared unique" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("model", [AdminUser, IndexedAdmin])
def test_unique_username_column_has_no_warning(
    caplog: pytest.LogCaptureFixture, model: type[object]
) -> None:
    with caplog.at_level("WARNING", logger="faststudio.auth"):
        ModelUserBackend(model)
    assert caplog.records == []


def test_dummy_hash_is_prepared_eagerly() -> None:
    from faststudio.auth.passwords import _dummy_hash  # noqa: PLC0415

    _dummy_hash.cache_clear()
    ModelUserBackend(AdminUser)
    assert _dummy_hash.cache_info().currsize == 1
