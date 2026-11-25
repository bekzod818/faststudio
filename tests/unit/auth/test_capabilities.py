"""Backend capabilities (ADR-0011 §1-3) and the shared `FlagAccountGuard`."""

from __future__ import annotations

import pickle
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from faststudio import Admin, AuthenticatedUser, ConfigurationError, ModelUserBackend
from faststudio.auth.capabilities import (
    ALL,
    AllPermissions,
    BackendCapabilities,
    Permissions,
    covers,
    holds,
)
from faststudio.auth.guard import FlagAccountGuard, WriteIntent
from tests._guards import guard_of
from tests._stubs import StubAuthBackend
from tests.factories.models import AdminUser, Team


class _Resolver:
    async def resolve(self, session: AsyncSession, user: AuthenticatedUser) -> Permissions:
        del session, user
        return ALL

    async def resolve_accounts(
        self, session: AsyncSession, keys: Sequence[object]
    ) -> Mapping[object, Permissions]:
        del session
        return dict.fromkeys(keys, frozenset[str]())


class _SyncResolver:
    def resolve(self, session: AsyncSession, user: AuthenticatedUser) -> Permissions:
        del session, user
        return ALL

    def resolve_accounts(self, session: AsyncSession, keys: Sequence[object]) -> object:
        del session, keys
        return {}


def _backend(**attributes: object) -> StubAuthBackend:
    backend = StubAuthBackend()
    for name, value in attributes.items():
        setattr(backend, name, value)
    return backend


def _admin(app: FastAPI, engine: AsyncEngine, secret_key: str, backend: object) -> Admin:
    return Admin(app, engine=engine, auth_backend=backend, secret_key=secret_key)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- permissions


def test_all_is_a_singleton() -> None:
    assert AllPermissions() is ALL
    assert repr(ALL) == "ALL"
    assert pickle.loads(pickle.dumps(ALL)) is ALL


@pytest.mark.parametrize(
    ("perms", "codename", "expected"),
    [
        (ALL, "anything.at_all", True),
        (frozenset({"posts.view"}), "posts.view", True),
        (frozenset({"posts.edit"}), "posts.view", True),  # edit implies view
        (frozenset({"posts.view"}), "posts.edit", False),
        (frozenset({"posts.edit"}), "tags.view", False),
        (frozenset({"posts.edit"}), "posts.publish", False),
        (frozenset({"a.b.edit"}), "a.b.view", True),
        (frozenset(), "posts.view", False),
    ],
)
def test_holds(perms: Permissions, codename: str, *, expected: bool) -> None:
    assert holds(perms, codename) is expected


def test_covers() -> None:
    assert covers(ALL, frozenset({"x.y"}))
    assert covers(frozenset({"a.edit"}), frozenset({"a.view", "a.edit"}))
    assert not covers(frozenset({"a.view"}), frozenset({"a.view", "a.edit"}))
    assert covers(frozenset(), frozenset())


# --------------------------------------------------------------------------- startup


def test_backends_without_capabilities_get_none(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    admin = _admin(app, engine, secret_key, StubAuthBackend())
    assert admin._capabilities == BackendCapabilities()


def test_model_user_backend_capabilities_are_used(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    backend = ModelUserBackend(AdminUser)
    admin = _admin(app, engine, secret_key, backend)
    assert admin._capabilities.account_guard is guard_of(backend)


def test_the_0_1_1_guard_methods_must_migrate(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    async def before_write(*args: object) -> None:
        del args

    legacy = _backend(guards=lambda m: True, check_model=lambda m: None, before_write=before_write)
    with pytest.raises(ConfigurationError, match="faststudio_capabilities"):
        _admin(app, engine, secret_key, legacy)


def test_an_unrelated_guards_attribute_is_ignored(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    _admin(app, engine, secret_key, _backend(guards=lambda m: True))


@pytest.mark.parametrize(
    ("capabilities", "match"),
    [
        ({"account_guard": object()}, "account_guard must implement AccountGuard"),
        ({"permissions": object()}, "permissions must implement PermissionBackend"),
        ({"permissions": _SyncResolver()}, "async resolve"),
        ({"permissions": _Resolver}, "PermissionBackend"),  # a class, not an instance
    ],
)
def test_invalid_capabilities_are_refused(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    capabilities: dict[str, Any],
    match: str,
) -> None:
    backend = _backend(faststudio_capabilities=BackendCapabilities(**capabilities))
    with pytest.raises(ConfigurationError, match=match):
        _admin(app, engine, secret_key, backend)


def test_capabilities_must_be_the_dataclass(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    backend = _backend(faststudio_capabilities={"permissions": _Resolver()})
    with pytest.raises(ConfigurationError, match="BackendCapabilities instance"):
        _admin(app, engine, secret_key, backend)


def test_valid_permissions_are_kept(
    app: FastAPI, engine: AsyncEngine, secret_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    resolver = _Resolver()
    backend = _backend(faststudio_capabilities=BackendCapabilities(permissions=resolver))
    with caplog.at_level("WARNING", logger="faststudio"):
        assert _admin(app, engine, secret_key, backend)._capabilities.permissions is resolver
    assert "no permission_schema: grants edited in the admin" in caplog.text


# --------------------------------------------------------------------------- FlagAccountGuard


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ((object, "id", ()), "not a mapped SQLAlchemy class"),
        (("AdminUser", "id", ()), "not a mapped SQLAlchemy class"),
        ((AdminUser, "username", ()), "not the primary key"),
        ((AdminUser, "id", ("nope",)), "'nope' is not a column"),
    ],
)
def test_flag_account_guard_validates(args: tuple[Any, ...], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        FlagAccountGuard(*args)


def test_flag_account_guard_validates_the_admin_flag() -> None:
    with pytest.raises(ConfigurationError, match="'is_root' is not a column"):
        FlagAccountGuard(AdminUser, "id", ("is_active",), admin_flag="is_root")


async def test_creating_an_account_never_locks_anyone_out() -> None:
    guard = FlagAccountGuard(AdminUser, "id", ("is_active", "is_admin"), admin_flag="is_admin")
    user = AuthenticatedUser(id="1", username="u1", auth_version="v")
    intent = WriteIntent(model=AdminUser, obj=AdminUser(), action="create", changes={})
    session: Any = None  # never touched for creates
    assert await guard.before_write(session, user, intent) is None
    assert guard.protected_fields(Team) == ("is_active", "is_admin")


def test_legacy_methods_next_to_capabilities_are_reported(
    app: FastAPI, engine: AsyncEngine, secret_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A ModelUserBackend subclass overriding the removed methods: they are never called."""

    class Legacy(ModelUserBackend):
        async def before_write(self, *args: object) -> None:
            del args

    with caplog.at_level("WARNING", logger="faststudio"):
        _admin(app, engine, secret_key, Legacy(AdminUser))
    assert "Legacy defines before_write, which FastStudio no longer calls" in caplog.text


def test_capability_dataclasses_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        BackendCapabilities(None, None)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- accounts (M18a)


class _Accounts:
    def __init__(self, validators: object = ()) -> None:
        self._validators = validators

    @property
    def password_validators(self) -> Any:
        return self._validators

    async def user_inputs(self, session: object, account_id: str) -> list[str]:
        del session, account_id
        return []

    async def check_password(self, session: object, account_id: str, password: str) -> bool:
        del session, account_id, password
        return False

    async def set_password(self, session: object, account_id: str, password: str) -> None:
        del session, account_id, password


@pytest.mark.parametrize(
    ("capabilities", "match"),
    [
        ({"accounts": object()}, "accounts must implement AccountManager"),
        ({"accounts": _Accounts("strong")}, "sequence of PasswordValidator"),
        ({"accounts": _Accounts([object()])}, "sequence of PasswordValidator"),
        ({"accounts": _Accounts(), "password_endpoints": "yes"}, "must be a bool"),
        ({"password_endpoints": True}, "needs accounts and an account_guard"),
        (
            {"accounts": _Accounts(), "password_endpoints": True},
            "needs accounts and an account_guard",
        ),
    ],
)
def test_invalid_account_capabilities_are_refused(
    app: FastAPI, engine: AsyncEngine, secret_key: str, capabilities: dict[str, Any], match: str
) -> None:
    backend = _backend(faststudio_capabilities=BackendCapabilities(**capabilities))
    with pytest.raises(ConfigurationError, match=match):
        _admin(app, engine, secret_key, backend)


@pytest.mark.parametrize(
    ("options", "match"),
    [
        ({"password_validators": "strong"}, "sequence of PasswordValidator"),
        ({"password_validators": [object()]}, "sequence of PasswordValidator"),
        ({"password_endpoints": 1}, "password_endpoints must be a bool"),
    ],
)
def test_model_user_backend_password_options(options: dict[str, Any], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        ModelUserBackend(AdminUser, **options)


async def test_model_user_backend_accounts(engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from faststudio import hash_password  # noqa: PLC0415
    from tests.factories.models import Base  # noqa: PLC0415

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["admin_users"]])
    accounts: Any = ModelUserBackend(AdminUser).faststudio_capabilities.accounts
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                AdminUser(id=1, username="ann", password_hash=hash_password("a long passphrase")),
                AdminUser(id=2, username="sso", password_hash="!sso-only"),
            ]
        )
        await session.flush()
        assert await accounts.user_inputs(session, "1") == ["ann"]
        assert await accounts.user_inputs(session, "99") == ()
        assert await accounts.user_inputs(session, "not-an-int") == ()
        assert await accounts.check_password(session, "1", "a long passphrase")
        assert not await accounts.check_password(session, "2", "anything")  # unusable hash
        assert not await accounts.check_password(session, "99", "anything")
        await accounts.set_password(session, "2", "now a real password")
        assert await accounts.check_password(session, "2", "now a real password")
        with pytest.raises(LookupError):
            await accounts.set_password(session, "99", "whatever it is")
