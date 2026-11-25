"""Account guard: other mappings of the user table, and non-integer primary keys."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from faststudio import Admin, AuthenticatedUser, ConfigurationError, ModelAdmin, ModelUserBackend
from faststudio.auth.guard import WriteAction, WriteIntent, WriteRefused
from tests._guards import guard_of
from tests._stubs import StubAuthBackend
from tests.factories.models import Team


class _Base(DeclarativeBase):
    pass


class Person(_Base):
    __tablename__ = "people"
    __mapper_args__ = {"polymorphic_on": "kind", "polymorphic_identity": "person"}  # noqa: RUF012

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Staff(Person):
    """Single-table subclass: the user model of the backend under test."""

    __mapper_args__ = {"polymorphic_identity": "staff"}  # noqa: RUF012


class Contractor(Staff):
    __mapper_args__ = {"polymorphic_identity": "contractor"}  # noqa: RUF012


class PersonView(_Base):
    """Another class mapped to the same table."""

    __table__ = Person.__table__
    __mapper_args__ = {"polymorphic_on": "kind", "polymorphic_identity": "view"}  # noqa: RUF012


class Account(_Base):
    """String primary key."""

    __tablename__ = "accounts"

    handle: Mapped[str] = mapped_column(String(50), primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)


class Member(_Base):
    """UUID primary key."""

    __tablename__ = "members"

    uid: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)


# ------------------------------------------------------------------ registration


@pytest.mark.parametrize("model", [Staff, Contractor, Team])
def test_user_model_subclasses_and_other_tables_are_allowed(model: type[Any]) -> None:
    guard_of(ModelUserBackend(Staff)).check_model(model)


@pytest.mark.parametrize("model", [Person, PersonView])
def test_other_mappings_of_the_user_table_are_refused(model: type[Any]) -> None:
    with pytest.raises(ConfigurationError, match=r"maps a table of Staff.*ADR-0009"):
        guard_of(ModelUserBackend(Staff)).check_model(model)


def test_register_refuses_a_mapping_that_bypasses_the_guard(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    admin = Admin(app, engine=engine, auth_backend=ModelUserBackend(Staff), secret_key=secret_key)

    class PersonAdmin(ModelAdmin, model=Person):
        list_display = ("id", "username")

    class StaffAdmin(ModelAdmin, model=Staff):
        list_display = ("id", "username")

    with pytest.raises(ConfigurationError, match="maps a table of Staff"):
        admin.register(PersonAdmin)
    admin.register(StaffAdmin)


def test_backends_without_a_guard_register_anything(
    app: FastAPI, engine: AsyncEngine, secret_key: str
) -> None:
    admin = Admin(app, engine=engine, auth_backend=StubAuthBackend(), secret_key=secret_key)

    class PersonAdmin(ModelAdmin, model=Person):
        list_display = ("id", "username")

    admin.register(PersonAdmin)


def test_non_mapped_classes_are_ignored() -> None:
    guard_of(ModelUserBackend(Staff)).check_model(object)
    assert not guard_of(ModelUserBackend(Staff)).guards(object)


# ------------------------------------------------------------------ primary key types


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/keys.db")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    yield engine
    await engine.dispose()


ALICE_UUID = uuid.UUID(int=1)
BOB_UUID = uuid.UUID(int=2)


async def _guarded_write(
    db: AsyncEngine, model: type[Any], pk: object, user_id: str, action: WriteAction
) -> None:
    backend = ModelUserBackend(model)
    async with AsyncSession(db) as session:
        session.add_all(
            [
                model(**{_pk_name(model): _key(model, "alice")}, username="alice"),
                model(**{_pk_name(model): _key(model, "bob")}, username="bob"),
            ]
        )
        await session.commit()
        obj = await session.get(model, pk)
        changes: dict[str, object] = {"is_admin": False} if action == "update" else {}
        intent = WriteIntent(model=model, obj=obj, action=action, changes=changes)
        user = AuthenticatedUser(id=user_id, username="alice", auth_version="v")
        check = await guard_of(backend).before_write(session, user, intent)
        assert check is not None
        await check()


def _pk_name(model: type[Any]) -> str:
    return "uid" if model is Member else "handle"


def _key(model: type[Any], name: str) -> object:
    if model is Member:
        return ALICE_UUID if name == "alice" else BOB_UUID
    return name


@pytest.mark.parametrize("action", ["update", "delete"])
@pytest.mark.parametrize(
    ("model", "own", "user_id"),
    [(Member, ALICE_UUID, str(ALICE_UUID)), (Account, "alice", "alice")],
)
async def test_own_row_is_recognised_for_uuid_and_string_keys(
    db: AsyncEngine, model: type[Any], own: object, user_id: str, action: WriteAction
) -> None:
    with pytest.raises(WriteRefused) as caught:
        await _guarded_write(db, model, own, user_id, action)
    assert caught.value.code == "self_lockout"


@pytest.mark.parametrize("action", ["update", "delete"])
@pytest.mark.parametrize(("model", "other"), [(Member, BOB_UUID), (Account, "bob")])
async def test_other_rows_with_uuid_and_string_keys_are_allowed(
    db: AsyncEngine, model: type[Any], other: object, action: WriteAction
) -> None:
    user_id = str(ALICE_UUID) if model is Member else "alice"
    await _guarded_write(db, model, other, user_id, action)
