"""`ModelUserBackend`: admins stored in the host application's user model (ADR-0004)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    UniqueConstraint,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapper
from starlette.requests import Request

from faststudio.auth.backend import AuthenticatedUser
from faststudio.auth.capabilities import BackendCapabilities
from faststudio.auth.guard import FlagAccountGuard
from faststudio.auth.passwords import (
    dummy_verify_async,
    hash_password_async,
    is_password_hash,
    prepare_dummy_hash,
    verify_password_async,
)
from faststudio.auth.validators import DEFAULT_VALIDATORS, PasswordValidator
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

    When the user model is registered in the admin, writes to it are guarded
    (ADR-0009): an admin cannot clear their own sign-in flags or delete their
    own row, and nobody can remove the last active admin.

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
        password_validators: Sequence[PasswordValidator] = DEFAULT_VALIDATORS,
        password_endpoints: bool = False,
    ) -> None:
        """Validate the model and column names; raises `ConfigurationError` on mistakes.

        Pass ``is_admin_field=None`` to let every active user sign in (only if
        every user of that table is meant to be an administrator).

        `password_validators` check new passwords set through FastStudio (CLI
        and, when enabled, the HTTP endpoints). ``password_endpoints=True``
        enables ``POST /auth/password`` and the set-password endpoint; it is
        off because every admin of this backend holds every permission, so
        any admin could then reset another admin's password.
        """
        candidate = cast("object", model)  # untyped callers can pass anything
        mapper: object = (
            sa_inspect(candidate, raiseerr=False) if isinstance(candidate, type) else None
        )
        if not isinstance(mapper, Mapper):
            msg = f"ModelUserBackend: {model!r} is not a mapped SQLAlchemy class."
            raise ConfigurationError(msg)
        self._model: type[Any] = model
        self._mapper: Mapper[Any] = mapper
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
        flags = tuple(f for f in (self._is_active_field, self._is_admin_field) if f is not None)
        validators = tuple(cast("Sequence[object]", password_validators))
        if isinstance(cast("object", password_validators), str) or not all(
            isinstance(v, PasswordValidator) for v in validators
        ):
            msg = "ModelUserBackend: password_validators must be a sequence of PasswordValidator."
            raise ConfigurationError(msg)
        if not isinstance(cast("object", password_endpoints), bool):
            msg = "ModelUserBackend: password_endpoints must be a bool."
            raise ConfigurationError(msg)
        inputs = [username_field, *(["email"] if _is_text_column(columns.get("email")) else [])]
        self._capabilities = BackendCapabilities(
            account_guard=FlagAccountGuard(
                model, self._pk_field, flags, admin_flag=self._is_admin_field
            ),
            accounts=_ModelAccounts(
                model,
                parse_pk=parser,
                password_field=password_field,
                input_fields=tuple(inputs),
                validators=cast("tuple[PasswordValidator, ...]", validators),
            ),
            password_endpoints=password_endpoints,
        )

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

    # ------------------------------------------------------------- capabilities

    @property
    def faststudio_capabilities(self) -> BackendCapabilities:
        """The account guard (ADR-0009) and password management.

        There is no permission backend, so every admin holds `ALL`.
        """
        return self._capabilities

    # ------------------------------------------------------------- AuthBackend

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
            await dummy_verify_async(password)
            return None
        row = rows[0]
        if not await verify_password_async(stored, password) or not self._allowed(row):
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


def _is_text_column(column: Column[Any] | None) -> bool:
    """Return True for an existing string or text column."""
    return column is not None and is_text(column)


class _ModelAccounts:
    """`AccountManager` over the host's user model (`ModelUserBackend`)."""

    def __init__(
        self,
        model: type[Any],
        *,
        parse_pk: Callable[[str], Any],
        password_field: str,
        input_fields: tuple[str, ...],
        validators: tuple[PasswordValidator, ...],
    ) -> None:
        self._model = model
        self._parse_pk = parse_pk
        self._password_field = password_field
        self._input_fields = input_fields
        self.password_validators: Sequence[PasswordValidator] = validators

    async def _row(self, session: AsyncSession, account_id: str) -> Any:  # noqa: ANN401 - host model
        try:
            pk = self._parse_pk(account_id)
        except ValueError:
            return None
        return await session.get(self._model, pk)

    async def user_inputs(self, session: AsyncSession, account_id: str) -> Sequence[str]:
        """Return the username (and email, if the model has one) of the account."""
        row = await self._row(session, account_id)
        if row is None:
            return ()
        values = (getattr(row, name) for name in self._input_fields)
        return [value for value in values if isinstance(value, str) and value]

    async def check_password(self, session: AsyncSession, account_id: str, password: str) -> bool:
        """Verify `password`; missing accounts and unusable hashes take the same time."""
        row = await self._row(session, account_id)
        stored = getattr(row, self._password_field) if row is not None else None
        if not isinstance(stored, str) or not is_password_hash(stored):
            return await dummy_verify_async(password)
        return await verify_password_async(stored, password)

    async def set_password(self, session: AsyncSession, account_id: str, password: str) -> None:
        """Hash and store `password` (the caller commits).

        Raises:
            LookupError: if the account does not exist.

        """
        row = await self._row(session, account_id)
        if row is None:
            msg = "No such account."
            raise LookupError(msg)
        setattr(row, self._password_field, await hash_password_async(password))
