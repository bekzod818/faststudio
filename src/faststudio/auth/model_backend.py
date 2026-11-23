"""`ModelUserBackend`: admins stored in the host application's user model (ADR-0004)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import Boolean, Column, Index, UniqueConstraint, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapper
from starlette.requests import Request

from faststudio.auth.backend import AuthenticatedUser
from faststudio.auth.passwords import (
    dummy_verify,
    is_password_hash,
    prepare_dummy_hash,
    verify_password,
)
from faststudio.exceptions import ConfigurationError
from faststudio.introspection._columns import base_type, is_text, mapped_columns
from faststudio.introspection._types import value_type

logger = logging.getLogger("faststudio.auth")


def _parse_int(raw: str) -> int:
    if not raw.isdigit():  # rejects "", "-1", "1.0", "+1", " 1"
        raise ValueError(raw)
    return int(raw)


def _is_unique(column: Column[Any]) -> bool:
    """Return True if a single-column unique constraint or index covers `column`."""
    if column.unique or column.primary_key:
        return True
    table = column.table
    for item in (*table.constraints, *table.indexes):
        if isinstance(item, UniqueConstraint | Index) and getattr(item, "unique", True):
            cols = list(item.columns)
            if len(cols) == 1 and cols[0] is column:
                return True
    return False


_PK_PARSERS: dict[str, Callable[[str], Any]] = {
    "integer": _parse_int,
    "uuid": uuid.UUID,
    "string": str,
    "text": str,
}


class ModelUserBackend:
    """Authenticate admins against the host's own SQLAlchemy user model.

    Only rows that are active (if ``is_active_field`` is set) **and** admins
    (if ``is_admin_field`` is set) may sign in. Passwords are verified with
    argon2 (see `faststudio.hash_password`). Unknown usernames still run a
    dummy verification, and inactive or non-admin rows still verify the
    password, so every failure takes the same time and returns ``None``.

    ``auth_version`` is derived from the password hash and both flags, so
    changing the password, deactivating the user or revoking admin rights
    invalidates all of their sessions.

    Example::

        Admin(app, engine=engine, auth_backend=ModelUserBackend(User))
    """

    def __init__(
        self,
        model: type[object],
        *,
        username_field: str = "username",
        password_field: str = "password_hash",  # noqa: S107 - a column name, not a password
        is_active_field: str | None = "is_active",
        is_admin_field: str | None = "is_admin",
    ) -> None:
        """Validate the model and column names; raises `ConfigurationError` on mistakes.

        Pass ``is_admin_field=None`` to let every active user sign in (only if
        every user of that table is meant to be an administrator).
        """
        candidate = cast("object", model)  # untyped callers can pass anything
        mapper: object = (
            sa_inspect(candidate, raiseerr=False) if isinstance(candidate, type) else None
        )
        if not isinstance(mapper, Mapper):
            msg = f"ModelUserBackend: {model!r} is not a mapped SQLAlchemy class."
            raise ConfigurationError(msg)
        self._model: type[Any] = model
        columns = mapped_columns(mapper)
        if username_field == password_field:
            msg = "ModelUserBackend: username_field and password_field must differ."
            raise ConfigurationError(msg)
        self._username = self._column(columns, "username_field", username_field)
        self._password = self._column(columns, "password_field", password_field)
        for option, column in (
            ("username_field", self._username),
            ("password_field", self._password),
        ):
            if not is_text(column):
                msg = f"ModelUserBackend: {option} must be a string column."
                raise ConfigurationError(msg)
        self._username_field = username_field
        self._password_field = password_field
        self._is_active_field = self._flag(columns, "is_active_field", is_active_field)
        self._is_admin_field = self._flag(columns, "is_admin_field", is_admin_field)
        if not _is_unique(self._username):
            logger.warning(
                "ModelUserBackend: %s.%s is not declared unique; duplicate usernames "
                "will be refused at login. Add unique=True or a unique index.",
                model.__name__,
                username_field,
            )
        prepare_dummy_hash()
        if len(mapper.primary_key) != 1:
            msg = "ModelUserBackend: the user model must have a single-column primary key."
            raise ConfigurationError(msg)
        pk_column = mapper.primary_key[0]
        self._pk_field = mapper.get_property_by_column(pk_column).key
        parser = _PK_PARSERS.get(value_type(cast("Column[Any]", pk_column)))
        if parser is None:
            msg = "ModelUserBackend: primary key must be an integer, UUID or string column."
            raise ConfigurationError(msg)
        self._parse_pk = parser

    @staticmethod
    def _column(columns: dict[str, Column[Any]], option: str, name: str) -> Column[Any]:
        column = columns.get(name)
        if column is None:
            msg = f"ModelUserBackend: {option}={name!r} is not a column of the model."
            raise ConfigurationError(msg)
        return column

    def _flag(self, columns: dict[str, Column[Any]], option: str, name: str | None) -> str | None:
        if name is None:
            return None
        column = self._column(columns, option, name)
        if not isinstance(base_type(column.type), Boolean):
            msg = f"ModelUserBackend: {option} must be a boolean column."
            raise ConfigurationError(msg)
        return name

    @staticmethod
    def _session_maker(request: Request) -> async_sessionmaker[AsyncSession]:
        context = getattr(request.app.state, "faststudio", None)
        if context is None:
            msg = "ModelUserBackend can only be used by a mounted faststudio.Admin."
            raise ConfigurationError(msg)
        maker: async_sessionmaker[AsyncSession] = context.session_maker
        return maker

    def _allowed(self, row: Any) -> bool:  # noqa: ANN401 - instance of the host model
        flags = (self._is_active_field, self._is_admin_field)
        return all(getattr(row, flag) is True for flag in flags if flag is not None)

    def _user(self, row: Any) -> AuthenticatedUser:  # noqa: ANN401 - instance of the host model
        state = "|".join(
            [
                str(getattr(row, self._password_field)),
                *(str(getattr(row, f)) for f in (self._is_active_field, self._is_admin_field) if f),
            ]
        )
        return AuthenticatedUser(
            id=str(getattr(row, self._pk_field)),
            username=str(getattr(row, self._username_field)),
            auth_version=hashlib.sha256(state.encode()).hexdigest()[:32],
        )

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        """Return the admin if the credentials match and the row may sign in."""
        statement = select(self._model).where(
            getattr(self._model, self._username_field) == username
        )
        async with self._session_maker(request)() as session:
            rows = (await session.execute(statement.limit(2))).scalars().all()
        stored = getattr(rows[0], self._password_field) if len(rows) == 1 else None
        # Unknown or ambiguous username, or no usable hash (NULL, legacy bcrypt,
        # SSO-only): spend the same time as a real check and refuse.
        if not isinstance(stored, str) or not is_password_hash(stored):
            dummy_verify(password)
            return None
        row = rows[0]
        if not verify_password(stored, password) or not self._allowed(row):
            return None
        return self._user(row)

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        """Reload the admin for a session; None if gone, inactive or no longer an admin."""
        try:
            pk = self._parse_pk(user_id)
        except ValueError:
            return None
        async with self._session_maker(request)() as session:
            row = await session.get(self._model, pk)
        if row is None or not self._allowed(row):
            return None
        return self._user(row)
