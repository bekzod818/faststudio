"""`PermissionSchema` validation and the registration checks (ADR-0011 §6, M17)."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, relationship

from faststudio import Admin, ConfigurationError, ModelAdmin
from faststudio.api._escalation import EscalationRules
from faststudio.auth.capabilities import BackendCapabilities
from faststudio.auth.guard import FlagAccountGuard
from tests.factories.auth_models import (
    SCHEMA,
    AuthGroup,
    AuthPermission,
    AuthUser,
    Folder,
    PermBackend,
    user_groups,
)


def _capabilities(schema: object, *, permissions: bool = True) -> BackendCapabilities:
    backend = PermBackend()
    guard = FlagAccountGuard(AuthUser, "id", ("is_active",), schema=schema)  # type: ignore[arg-type]
    return BackendCapabilities(account_guard=guard, permissions=backend if permissions else None)


def test_the_test_schema_compiles() -> None:
    rules = EscalationRules.from_capabilities(_capabilities(SCHEMA))
    assert rules is not None
    assert rules.side_of(AuthUser) == "user"
    assert rules.side_of(AuthGroup) == "group"
    assert rules.side_of(Folder) is None
    assert set(rules.links["user"]) == {"permissions", "groups"}
    assert rules.codename.key == "codename"


def test_no_schema_means_no_rules() -> None:
    assert EscalationRules.from_capabilities(BackendCapabilities()) is None
    assert EscalationRules.from_capabilities(_capabilities(None)) is None


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"user_permissions": "nope"}, "has no relationship 'nope'"),
        ({"user_permissions": "groups"}, "targets AuthGroup, not AuthPermission"),
        ({"codename_field": "label"}, "'label' is not a column"),
        ({"user_model": object}, "not a mapped SQLAlchemy class"),
        (
            {
                "group_model": None,
                "group_permissions": None,
                "group_users": None,
                "permission_groups": None,
            },
            "user_groups needs a group_model",
        ),
        ({"group_permissions": None, "permission_groups": None}, "must name group_permissions"),
    ],
)
def test_invalid_schemas_fail_at_startup(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        EscalationRules.from_capabilities(_capabilities(dataclasses.replace(SCHEMA, **changes)))


def test_a_schema_needs_a_permission_backend() -> None:
    with pytest.raises(ConfigurationError, match=r"needs BackendCapabilities\.permissions"):
        EscalationRules.from_capabilities(_capabilities(SCHEMA, permissions=False))


def test_a_schema_must_be_the_dataclass() -> None:
    with pytest.raises(ConfigurationError, match="must return a PermissionSchema"):
        EscalationRules.from_capabilities(_capabilities({"user_model": AuthUser}))


def test_relationships_must_be_plain() -> None:
    class Base(DeclarativeBase):
        pass

    links = Table(
        "x_links",
        Base.metadata,
        Column("user_id", ForeignKey(AuthUser.__table__.c.id), primary_key=True),
        Column("permission_id", ForeignKey(AuthPermission.__table__.c.id), primary_key=True),
        Column("level", Integer),  # no default: not plain
    )

    class XUser(Base):
        __table__ = AuthUser.__table__
        perms = relationship(AuthPermission, secondary=links)

    schema = dataclasses.replace(
        SCHEMA,
        user_model=XUser,
        user_permissions="perms",
        user_groups=None,
        group_users=None,
        permission_users=None,
    )
    with pytest.raises(ConfigurationError, match=r"XUser\.perms is not usable"):
        EscalationRules.from_capabilities(_capabilities(schema))


# --------------------------------------------------------------------------- registration


def test_a_mapping_of_an_association_table_is_refused() -> None:
    rules = EscalationRules.from_capabilities(_capabilities(SCHEMA))
    assert rules is not None

    class Base(DeclarativeBase):
        pass

    class UserGroupLink(Base):
        __table__ = user_groups

    registered: Any = SimpleNamespace(model=UserGroupLink, many_to_many={})
    with pytest.raises(ConfigurationError, match="maps a permission association table"):
        rules.check_model(registered)


@pytest.fixture
def admin(app: FastAPI, engine: AsyncEngine, secret_key: str) -> Admin:
    return Admin(app, engine=engine, auth_backend=PermBackend(), secret_key=secret_key)


def test_undeclared_writable_sides_are_refused(admin: Admin) -> None:
    """A second relationship over a declared table is a side the rules do not know."""
    shadow = type(
        "ShadowAdmin",
        (ModelAdmin,),
        {"identity": "users", "exclude": ("password_hash",), "many_to_many": ("shadow_groups",)},
        model=AuthUser,
    )
    with pytest.raises(ConfigurationError, match="not declared in the backend's PermissionSchema"):
        admin.register(shadow)
    readonly = type(
        "ReadonlyShadowAdmin",
        (ModelAdmin,),
        {
            "identity": "users",
            "exclude": ("password_hash",),
            "many_to_many": ("shadow_groups", "groups"),
            "readonly_fields": ("shadow_groups",),
        },
        model=AuthUser,
    )
    admin.register(readonly)


# --------------------------------------------------------------------------- the closed form


@pytest.fixture
async def auth_db(tmp_path: Any) -> Any:
    from sqlalchemy import insert  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415

    from tests.factories.auth_models import AuthBase, group_permissions  # noqa: PLC0415

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/rules.db")
    async with engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.create_all)
    async with AsyncSession(engine) as session:
        session.add_all([AuthPermission(id=1, codename="docs.view"), AuthGroup(id=1, name="g")])
        session.add(AuthGroup(id=2, name="empty"))
        session.add(AuthUser(id=1, username="u"))
        await session.flush()
        await session.execute(insert(group_permissions), [{"group_id": 1, "permission_id": 1}])
        await session.commit()
    yield engine
    await engine.dispose()


async def test_group_grants_are_read_from_the_reverse_side_too(auth_db: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    reverse_only = dataclasses.replace(SCHEMA, group_permissions=None)
    rules = EscalationRules.from_capabilities(_capabilities(reverse_only))
    assert rules is not None
    async with AsyncSession(auth_db) as session:
        assert await rules._group_codenames(session, [1]) == {"docs.view"}
        assert await rules._group_codenames(session, [2]) == set()


async def test_joining_a_group_that_grants_nothing_needs_no_lookup(auth_db: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from faststudio.api._escalation import _new_for  # noqa: PLC0415

    class Exploding(PermBackend):
        async def resolve_accounts(self, session: Any, keys: Any) -> Any:
            raise AssertionError("not needed")

    async with AsyncSession(auth_db) as session:
        assert await _new_for(session, Exploding(), [1], set()) == set()


async def test_without_a_schema_only_the_account_rules_apply(auth_db: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from faststudio.api._escalation import check_escalation  # noqa: PLC0415
    from faststudio.auth.guard import WriteIntent  # noqa: PLC0415

    capabilities = _capabilities(None)
    registered: Any = SimpleNamespace(model=Folder, pk_field="id")
    intent = WriteIntent(model=Folder, obj=Folder(id=1), action="update", changes={})
    async with AsyncSession(auth_db) as session:
        await check_escalation(
            session,
            capabilities=capabilities,
            rules=None,
            actor=frozenset({"folders.edit"}),
            registered=registered,
            intent=intent,
            added={},
        )
