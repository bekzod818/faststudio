"""ModelUserBackend's account-safety guard (ADR-0009), called directly."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from faststudio import AuthenticatedUser, ModelUserBackend
from faststudio.auth.guard import AccountGuard, WriteAction, WriteIntent, WriteRefused
from tests._guards import guard_of
from tests.factories.models import AdminUser, Base, Team

HASH = "not-a-password-hash"  # the guard never verifies passwords


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/guard.db")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables["admin_users"], Base.metadata.tables["teams"]],
        )
    yield engine
    await engine.dispose()


async def _seed(db: AsyncEngine, *rows: tuple[int, bool, bool]) -> None:
    async with async_sessionmaker(db)() as session:
        session.add_all(
            AdminUser(id=pk, username=f"u{pk}", password_hash=HASH, is_active=a, is_admin=b)
            for pk, a, b in rows
        )
        await session.commit()


def _user(pk: int | str) -> AuthenticatedUser:
    return AuthenticatedUser(id=str(pk), username=f"u{pk}", auth_version="v")


async def _write(
    db: AsyncEngine,
    backend: ModelUserBackend,
    user: AuthenticatedUser,
    pk: int,
    action: WriteAction,
    *,
    changes: dict[str, Any] | None = None,
) -> None:
    """Run the guard around a real write the way the API does, then commit."""
    async with AsyncSession(db) as session:
        obj = await session.get(AdminUser, pk)
        assert obj is not None
        intent = WriteIntent(model=AdminUser, obj=obj, action=action, changes=changes or {})
        check = await guard_of(backend).before_write(session, user, intent)
        if action == "delete":
            await session.delete(obj)
        else:
            for name, value in (changes or {}).items():
                setattr(obj, name, value)
        await session.flush()
        if check is not None:
            await check()
        await session.commit()


async def _admins(db: AsyncEngine) -> dict[int, tuple[bool, bool]]:
    async with AsyncSession(db) as session:
        rows = (await session.execute(AdminUser.__table__.select())).all()
    return {row.id: (row.is_active, row.is_admin) for row in rows}


def test_model_user_backend_provides_a_flag_account_guard() -> None:
    backend = ModelUserBackend(AdminUser)
    assert not isinstance(backend, AccountGuard)  # a capability now, not duck-typed methods
    assert backend.faststudio_capabilities.permissions is None  # every admin holds ALL
    guard = guard_of(backend)
    assert isinstance(guard, AccountGuard)
    assert guard.guards(AdminUser)
    assert not guard.guards(Team)
    assert guard.admin_flag(AdminUser) == "is_admin"
    assert guard.admin_flag(Team) is None
    assert backend.faststudio_capabilities.permission_schema is None
    assert guard_of(ModelUserBackend(AdminUser, is_admin_field=None)).admin_flag(AdminUser) is None


# ------------------------------------------------------------------ own account


@pytest.mark.parametrize("field", ["is_admin", "is_active"])
async def test_cannot_remove_own_flag(db: AsyncEngine, field: str) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    with pytest.raises(WriteRefused) as caught:
        await _write(db, ModelUserBackend(AdminUser), _user(1), 1, "update", changes={field: False})
    assert caught.value.code == "self_lockout"
    assert (await _admins(db))[1] == (True, True)


async def test_resending_own_flags_unchanged_is_allowed(db: AsyncEngine) -> None:
    await _seed(db, (1, True, True))
    changes = {"is_admin": True, "is_active": True, "username": "renamed"}
    await _write(db, ModelUserBackend(AdminUser), _user(1), 1, "update", changes=changes)
    assert (await _admins(db))[1] == (True, True)


async def test_cannot_delete_own_account(db: AsyncEngine) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    with pytest.raises(WriteRefused) as caught:
        await _write(db, ModelUserBackend(AdminUser), _user(1), 1, "delete")
    assert caught.value.code == "self_lockout"
    assert 1 in await _admins(db)


async def test_own_flags_are_protected_even_without_admin_flag(db: AsyncEngine) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    backend = ModelUserBackend(AdminUser, is_admin_field=None)
    with pytest.raises(WriteRefused, match="self_lockout"):
        await _write(db, backend, _user(1), 1, "update", changes={"is_active": False})
    # is_admin is not a sign-in flag for this backend: changing it is not a lockout.
    await _write(db, backend, _user(1), 1, "update", changes={"is_admin": False})


# ------------------------------------------------------------------ other accounts


async def test_can_demote_another_admin_while_one_remains(db: AsyncEngine) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    await _write(
        db, ModelUserBackend(AdminUser), _user(1), 2, "update", changes={"is_admin": False}
    )
    await _write(db, ModelUserBackend(AdminUser), _user(1), 2, "delete")
    assert await _admins(db) == {1: (True, True)}


@pytest.mark.parametrize(
    ("action", "changes"),
    [("update", {"is_admin": False}), ("update", {"is_active": False}), ("delete", None)],
)
async def test_last_active_admin_cannot_be_removed(
    db: AsyncEngine, action: WriteAction, changes: dict[str, Any] | None
) -> None:
    # Admin 2 is inactive and 3 is not an admin: only 1 is an active admin. The
    # requester (99) is not in this table, as with a backend that keeps admins elsewhere.
    await _seed(db, (1, True, True), (2, False, True), (3, True, False))
    with pytest.raises(WriteRefused) as caught:
        await _write(db, ModelUserBackend(AdminUser), _user(99), 1, action, changes=changes)
    assert caught.value.code == "last_admin"


@pytest.mark.parametrize("changes", [{"is_admin": True}, {"is_active": True}, {"username": "x"}])
async def test_writes_that_cannot_remove_an_admin_skip_the_check(
    db: AsyncEngine, changes: dict[str, Any]
) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    async with AsyncSession(db) as session:
        obj = await session.get(AdminUser, 2)
        intent = WriteIntent(model=AdminUser, obj=obj, action="update", changes=changes)
        assert (
            await guard_of(ModelUserBackend(AdminUser)).before_write(session, _user(1), intent)
            is None
        )


@pytest.mark.parametrize(("action", "changes"), [("update", {"is_admin": False}), ("delete", None)])
async def test_removals_are_checked_whatever_the_loaded_state(
    db: AsyncEngine, action: WriteAction, changes: dict[str, Any] | None
) -> None:
    # Row 2 was loaded as a non-admin, but the decision must not trust it.
    await _seed(db, (1, True, True), (2, True, False))
    async with AsyncSession(db) as session:
        obj = await session.get(AdminUser, 2)
        intent = WriteIntent(model=AdminUser, obj=obj, action=action, changes=changes or {})
        check = await guard_of(ModelUserBackend(AdminUser)).before_write(session, _user(1), intent)
        assert check is not None
        await check()  # admin 1 remains


async def test_stale_loaded_row_cannot_remove_the_last_admin(db: AsyncEngine) -> None:
    """Y is loaded inactive, then activated while X is demoted: demoting Y must fail."""
    await _seed(db, (1, True, True), (2, False, True))  # X = 1, Y = 2
    backend = ModelUserBackend(AdminUser)
    async with AsyncSession(db, expire_on_commit=False) as session:
        stale_y = await session.get(AdminUser, 2)  # loaded as inactive
        assert stale_y is not None
        await session.commit()  # end the read so other writers may commit (SQLite)
        await _write(db, backend, _user(99), 2, "update", changes={"is_active": True})
        await _write(db, backend, _user(99), 1, "update", changes={"is_admin": False})
        intent = WriteIntent(
            model=AdminUser, obj=stale_y, action="update", changes={"is_admin": False}
        )
        check = await guard_of(backend).before_write(session, _user(99), intent)
        assert check is not None
        stale_y.is_admin = False
        await session.flush()
        with pytest.raises(WriteRefused) as caught:
            await check()
        assert caught.value.code == "last_admin"
        await session.rollback()
    assert await _admins(db) == {1: (True, False), 2: (True, True)}


async def test_without_flags_every_row_is_an_admin(db: AsyncEngine) -> None:
    await _seed(db, (1, False, False), (2, False, False))
    backend = ModelUserBackend(AdminUser, is_active_field=None, is_admin_field=None)
    # is_admin is not a sign-in flag for this backend.
    await _write(db, backend, _user(99), 2, "update", changes={"is_admin": True})
    await _write(db, backend, _user(99), 2, "delete")
    with pytest.raises(WriteRefused) as caught:
        await _write(db, backend, _user(99), 1, "delete")
    assert caught.value.code == "last_admin"


def test_refusal_carries_code_and_safe_message() -> None:
    message = "At least one active admin must remain."
    refused = WriteRefused("last_admin", message)
    assert (refused.code, refused.message) == ("last_admin", message)
    assert str(refused) == "last_admin"


async def test_unknown_actions_are_refused(db: AsyncEngine) -> None:
    await _seed(db, (1, True, True), (2, True, True))
    async with AsyncSession(db) as session:
        obj = await session.get(AdminUser, 2)
        intent = WriteIntent(model=AdminUser, obj=obj, action="bulk_update", changes={})  # type: ignore[arg-type]  # a future action
        with pytest.raises(AssertionError):
            await guard_of(ModelUserBackend(AdminUser)).before_write(session, _user(1), intent)
