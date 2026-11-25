"""Users, groups and permissions for authorization tests (ADR-0011, M17).

A small stand-in for M18's `contrib.auth`: plain many-to-many tables on both
sides, and `PermBackend`, an auth backend with the account-guard and
permission capabilities (superusers hold `ALL`; others resolve in one query).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    cast,
    literal,
    null,
    select,
    union,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from starlette.requests import Request

from faststudio import AuthenticatedUser
from faststudio.auth.capabilities import (
    ALL,
    BackendCapabilities,
    Permissions,
    PermissionSchema,
)
from faststudio.auth.guard import FlagAccountGuard
from faststudio.auth.passwords import verify_password_async


class AuthBase(DeclarativeBase):
    pass


user_groups = Table(
    "t_user_groups",
    AuthBase.metadata,
    Column("user_id", ForeignKey("t_users.id"), primary_key=True),
    Column("group_id", ForeignKey("t_groups.id"), primary_key=True),
)
user_permissions = Table(
    "t_user_permissions",
    AuthBase.metadata,
    Column("user_id", ForeignKey("t_users.id"), primary_key=True),
    Column("permission_id", ForeignKey("t_permissions.id"), primary_key=True),
)
group_permissions = Table(
    "t_group_permissions",
    AuthBase.metadata,
    Column("group_id", ForeignKey("t_groups.id"), primary_key=True),
    Column("permission_id", ForeignKey("t_permissions.id"), primary_key=True),
)


class AuthPermission(AuthBase):
    __tablename__ = "t_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    codename: Mapped[str] = mapped_column(String(100), unique=True)
    groups: Mapped[list[AuthGroup]] = relationship(
        secondary=group_permissions, back_populates="permissions"
    )
    users: Mapped[list[AuthUser]] = relationship(
        secondary=user_permissions, back_populates="permissions"
    )


class AuthGroup(AuthBase):
    __tablename__ = "t_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    permissions: Mapped[list[AuthPermission]] = relationship(
        secondary=group_permissions, back_populates="groups"
    )
    users: Mapped[list[AuthUser]] = relationship(secondary=user_groups, back_populates="groups")


class AuthUser(AuthBase):
    __tablename__ = "t_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="!")  # unusable
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    groups: Mapped[list[AuthGroup]] = relationship(secondary=user_groups, back_populates="users")
    permissions: Mapped[list[AuthPermission]] = relationship(
        secondary=user_permissions, back_populates="users"
    )
    #: A second, undeclared side over `user_groups`: registering it writable must fail.
    shadow_groups: Mapped[list[AuthGroup]] = relationship(
        secondary=user_groups, overlaps="groups,users"
    )


# --------------------------------------------------------------------------- content


class Folder(AuthBase):
    __tablename__ = "t_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))


doc_badges = Table(
    "t_doc_badges",
    AuthBase.metadata,
    Column("doc_id", ForeignKey("t_docs.id"), primary_key=True),
    Column("badge_id", ForeignKey("t_badges.id"), primary_key=True),
)


class Badge(AuthBase):
    __tablename__ = "t_badges"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))


class Doc(AuthBase):
    __tablename__ = "t_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    level: Mapped[int] = mapped_column(Integer, default=0)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("t_folders.id"), nullable=True)
    badges: Mapped[list[Badge]] = relationship(secondary=doc_badges)


SCHEMA = PermissionSchema(
    user_model=AuthUser,
    permission_model=AuthPermission,
    codename_field="codename",
    user_permissions="permissions",
    group_model=AuthGroup,
    user_groups="groups",
    group_permissions="permissions",
    group_users="users",
    permission_groups="groups",
    permission_users="users",
)


class PermBackend:
    """Auth backend with users, groups and permissions (a test stand-in for contrib)."""

    def __init__(self) -> None:
        self._capabilities = BackendCapabilities(
            account_guard=FlagAccountGuard(
                AuthUser,
                "id",
                ("is_active", "is_superuser"),
                admin_flag="is_superuser",
            ),
            permissions=self,
            permission_schema=SCHEMA,
        )

    @property
    def faststudio_capabilities(self) -> BackendCapabilities:
        return self._capabilities

    @staticmethod
    def _maker(request: Request) -> async_sessionmaker[AsyncSession]:
        maker: async_sessionmaker[AsyncSession] = request.app.state.faststudio.session_maker
        return maker

    @staticmethod
    def _user(row: AuthUser) -> AuthenticatedUser:
        state = f"{row.password_hash}|{row.is_active}|{row.is_superuser}"
        return AuthenticatedUser(id=str(row.id), username=row.username, auth_version=state)

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        async with self._maker(request)() as session:
            row = await session.scalar(select(AuthUser).where(AuthUser.username == username))
        if row is None or not row.is_active:
            return None
        if not await verify_password_async(row.password_hash, password):
            return None
        return self._user(row)

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        async with self._maker(request)() as session:
            row = await session.get(AuthUser, int(user_id))
        return self._user(row) if row is not None and row.is_active else None

    # ------------------------------------------------------------- PermissionBackend

    async def resolve(self, session: AsyncSession, user: AuthenticatedUser) -> Permissions:
        return (await self.resolve_accounts(session, [int(user.id)])).get(int(user.id), frozenset())

    async def resolve_accounts(
        self, session: AsyncSession, keys: Sequence[object]
    ) -> Mapping[object, Permissions]:
        """One query: superuser flags and direct and group codenames of `keys`."""
        direct = (
            select(user_permissions.c.user_id.label("uid"), AuthPermission.codename)
            .join(AuthPermission, AuthPermission.id == user_permissions.c.permission_id)
            .where(user_permissions.c.user_id.in_(keys))
        )
        grouped = (
            select(user_groups.c.user_id.label("uid"), AuthPermission.codename)
            .join(group_permissions, group_permissions.c.group_id == user_groups.c.group_id)
            .join(AuthPermission, AuthPermission.id == group_permissions.c.permission_id)
            .where(user_groups.c.user_id.in_(keys))
        )
        # Superusers: one row with a NULL codename, meaning ALL.
        superusers = select(
            AuthUser.id.label("uid"), cast(null(), String(100)).label("codename")
        ).where(AuthUser.id.in_(keys), AuthUser.is_superuser.is_(True))
        # Every existing account gets an entry, also without any codename.
        existing = select(
            AuthUser.id.label("uid"), literal("", String(100)).label("codename")
        ).where(AuthUser.id.in_(keys))
        rows = (await session.execute(union(direct, grouped, superusers, existing))).all()
        result: dict[object, Permissions] = {}
        found: dict[Any, set[str]] = {}
        for uid, codename in rows:
            if codename is None:
                result[uid] = ALL
            elif codename:
                found.setdefault(uid, set()).add(codename)
            else:
                found.setdefault(uid, set())
        for uid, codenames in found.items():
            result.setdefault(uid, frozenset(codenames))
        return result
