"""Users, groups and permissions stored by FastStudio (ADR-0011 §8).

These are **admin staff accounts**: every active user can sign in to the
admin. Never reuse these tables for your application's end users.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship, validates

from faststudio.exceptions import ConfigurationError

__all__ = [
    "MAX_USERNAME_LENGTH",
    "AuthModels",
    "GroupMixin",
    "PermissionMixin",
    "UserMixin",
    "normalize_username",
]

MAX_USERNAME_LENGTH = 150
_PREFIX = re.compile(r"[a-z][a-z0-9_]{0,30}|")
#: Declarative bases that already have the models (one set per base).
_USED: WeakSet[type] = WeakSet()


def normalize_username(username: str) -> str:
    """Return the comparison form of a username: NFKC, then case-folded.

    Two usernames with the same normalized form are the same account, so
    ``Admin``, ``admin`` and its full-width form cannot coexist.
    """
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", username).casefold())


def unusable_password() -> str:
    """Return a stored value no password ever matches (not an argon2 hash)."""
    return "!" + secrets.token_urlsafe(16)


def new_session_token() -> str:
    """Return a random token; changing it signs the account out everywhere (ADR-0013)."""
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


class UserMixin:
    """Columns of `FastStudioUser`; relationships are added by `AuthModels`."""

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(MAX_USERNAME_LENGTH), unique=True)
    #: `normalize_username(username)`, kept in sync on assignment; unique, used to sign in.
    username_normalized: Mapped[str] = mapped_column(String(MAX_USERNAME_LENGTH), unique=True)
    email: Mapped[str] = mapped_column(String(254), default="")
    #: argon2id hash, or an unusable marker (new users cannot sign in yet).
    password_hash: Mapped[str] = mapped_column(String(255), default=unusable_password)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Holds every permission; the last active superuser cannot be removed.
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    session_token: Mapped[str] = mapped_column(String(64), default=new_session_token)
    date_joined: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    if TYPE_CHECKING:

        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401 - declarative constructor
            ...

        groups: Mapped[list[GroupMixin]]
        permissions: Mapped[list[PermissionMixin]]

    @validates("username")
    def _normalize(self, key: str, value: str) -> str:
        del key
        stored = unicodedata.normalize("NFKC", value)
        self.username_normalized = normalize_username(stored)
        return stored


class GroupMixin:
    """Columns of `FastStudioGroup`."""

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)

    if TYPE_CHECKING:

        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401 - declarative constructor
            ...

        users: Mapped[list[UserMixin]]
        permissions: Mapped[list[PermissionMixin]]


class PermissionMixin:
    """Columns of `FastStudioPermission`: one codename, ``"<identity>.<action>"``."""

    id: Mapped[int] = mapped_column(primary_key=True)
    codename: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")

    if TYPE_CHECKING:

        def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401 - declarative constructor
            ...

        users: Mapped[list[UserMixin]]
        groups: Mapped[list[GroupMixin]]


def _link(name: str, metadata: Any, left: tuple[str, str], right: tuple[str, str]) -> Table:  # noqa: ANN401 - MetaData
    """Build an association table: (column, referenced table) per side, cascading deletes."""
    return Table(
        name,
        metadata,
        *(
            Column(column, ForeignKey(f"{table}.id", ondelete="CASCADE"), primary_key=True)
            for column, table in (left, right)
        ),
    )


def _sync_username(mapper: Any, connection: Any, target: UserMixin) -> None:  # noqa: ANN401
    del mapper, connection
    target.username_normalized = normalize_username(target.username)


class AuthModels:
    """Declare the users, groups and permissions on your declarative `Base`.

    Example::

        class Base(DeclarativeBase):
            pass

        auth = AuthModels(Base)  # tables faststudio_user, faststudio_group, ...
        backend = DatabaseAuthBackend(auth)

    Create the tables with your migrations (Alembic autogenerate sees them) or
    ``Base.metadata.create_all``. Calling it twice on the same `Base` raises
    `ConfigurationError`.

    Attributes:
        user: The mapped `FastStudioUser` class.
        group: The mapped `FastStudioGroup` class.
        permission: The mapped `FastStudioPermission` class.
        user_groups: The user ↔ group association table.
        user_permissions: The user ↔ permission association table.
        group_permissions: The group ↔ permission association table.

    """

    def __init__(self, base: type[Any], *, table_prefix: str = "faststudio_") -> None:
        """Map the models on `base` (a SQLAlchemy 2.0 declarative base)."""
        candidate: object = base  # untyped callers
        metadata = getattr(candidate, "metadata", None)
        if (
            not isinstance(candidate, type)
            or metadata is None
            or not hasattr(candidate, "registry")
        ):
            msg = "AuthModels: base must be a SQLAlchemy declarative base class."
            raise ConfigurationError(msg)
        prefix_value: object = table_prefix  # untyped callers
        if not isinstance(prefix_value, str) or not _PREFIX.fullmatch(prefix_value):
            msg = "AuthModels: table_prefix must be empty or match [a-z][a-z0-9_]{0,30}."
            raise ConfigurationError(msg)
        if issubclass(base, MappedAsDataclass):
            msg = "AuthModels: dataclass-mapped bases (MappedAsDataclass) are not supported."
            raise ConfigurationError(msg)
        if base in _USED:
            msg = f"AuthModels was already called for {base.__name__}."
            raise ConfigurationError(msg)
        prefix = table_prefix
        user_t, group_t, perm_t = f"{prefix}user", f"{prefix}group", f"{prefix}permission"
        self.user_groups = _link(
            f"{prefix}user_groups", metadata, ("user_id", user_t), ("group_id", group_t)
        )
        self.user_permissions = _link(
            f"{prefix}user_permissions", metadata, ("user_id", user_t), ("permission_id", perm_t)
        )
        self.group_permissions = _link(
            f"{prefix}group_permissions", metadata, ("group_id", group_t), ("permission_id", perm_t)
        )
        self.user: type[UserMixin] = type(
            "FastStudioUser", (UserMixin, base), {"__tablename__": user_t}
        )
        self.group: type[GroupMixin] = type(
            "FastStudioGroup", (GroupMixin, base), {"__tablename__": group_t}
        )
        self.permission: type[PermissionMixin] = type(
            "FastStudioPermission",
            (PermissionMixin, base),
            {"__tablename__": perm_t},
        )
        user, group, permission = self.user, self.group, self.permission
        # add_property maps the relationships on any declarative base (metaclass or not).
        sides = [
            (user, "groups", group, self.user_groups, "users"),
            (user, "permissions", permission, self.user_permissions, "users"),
            (group, "users", user, self.user_groups, "groups"),
            (group, "permissions", permission, self.group_permissions, "groups"),
            (permission, "users", user, self.user_permissions, "permissions"),
            (permission, "groups", group, self.group_permissions, "permissions"),
        ]
        for owner, name, target, secondary, back in sides:
            sa_inspect(owner).add_property(
                name, relationship(target, secondary=secondary, back_populates=back)
            )
        # The sign-in key always follows `username`, whatever was assigned to it
        # (an admin exposing the column, a stale value): recomputed on every flush.
        event.listen(user, "before_insert", _sync_username, propagate=True)
        event.listen(user, "before_update", _sync_username, propagate=True)
        _USED.add(base)
