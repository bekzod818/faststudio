"""Account-safety guard: a capability of auth backends (ADR-0009, public since ADR-0011).

The write API asks the backend's guard whether a write to the model that
stores its admins would lock someone out, before the write is flushed, and
again after the flush in the same transaction. A backend provides one through
`BackendCapabilities.account_guard`; `FlagAccountGuard` covers the common case
of boolean sign-in flags on the user row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, assert_never, cast, runtime_checkable

from sqlalchemy import ColumnElement, and_, select, true
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper

from faststudio.auth.backend import AuthenticatedUser
from faststudio.auth.capabilities import PermissionSchema
from faststudio.exceptions import ConfigurationError

__all__ = [
    "AccountGuard",
    "FlagAccountGuard",
    "PostWriteCheck",
    "RefusalCode",
    "WriteAction",
    "WriteIntent",
    "WriteRefused",
]

WriteAction = Literal["create", "update", "delete"]
RefusalCode = Literal["self_lockout", "last_admin"]

#: Runs after the write is flushed, before commit; raises `WriteRefused` to undo it.
PostWriteCheck = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WriteIntent:
    """A pending write.

    Attributes:
        model: The registered model written to.
        obj: The loaded object (for creates: the new, not yet flushed object).
        action: ``"create"``, ``"update"`` or ``"delete"``.
        changes: The validated values sent (empty for deletes). Many-to-many
            fields appear as lists of target keys.

    """

    model: type[Any]
    obj: Any
    action: WriteAction
    changes: Mapping[str, object]


class WriteRefused(Exception):  # noqa: N818 - a refusal, not an internal error
    """The guard refused a write; the API answers 409 with `code`.

    `message` is shown to the admin and must not contain stored values.
    """

    def __init__(self, code: RefusalCode, message: str) -> None:
        """Create a refusal with a contract error code and a safe message."""
        super().__init__(code)
        self.code: RefusalCode = code
        self.message = message


@runtime_checkable
class AccountGuard(Protocol):
    """Capability: protect the accounts that can sign in to the admin."""

    def guards(self, model: type[Any]) -> bool:
        """Return True if writes to `model` must be checked."""
        ...

    def check_model(self, model: type[Any]) -> None:
        """Raise `ConfigurationError` at `register()` if `model` would bypass the guard.

        For example another class mapped to the table that holds the accounts.
        """
        ...

    def protected_fields(self, model: type[Any]) -> tuple[str, ...]:
        """Return the fields of a guarded model an admin cannot change on their own record."""
        ...

    def admin_flag(self, model: type[Any]) -> str | None:
        """Return the superuser-like flag of a guarded model, if it has one.

        Only a user holding `ALL` may change it (ADR-0011 §6).
        """
        ...

    def permission_schema(self) -> PermissionSchema | None:
        """Return where users, groups and permissions are stored, if the backend has them."""
        ...

    async def before_write(
        self, session: AsyncSession, user: AuthenticatedUser, intent: WriteIntent
    ) -> PostWriteCheck | None:
        """Check a write before it is applied, in the request's transaction.

        Raise `WriteRefused` to refuse it outright. To check the outcome (for
        example the number of remaining admins), lock what the check reads and
        return a callable that runs after the flush, in the same transaction.
        """
        ...


class FlagAccountGuard:
    """An `AccountGuard` for user rows that may sign in when boolean flags are true.

    An admin is a row whose every flag is true; permissions granted by groups
    do not count. The guard refuses writes that would make the signed-in admin
    lose their own access (`self_lockout`) and writes that leave no active
    admin (`last_admin`), including under concurrent requests.

    Example::

        FlagAccountGuard(User, "id", ("is_active", "is_superuser"), admin_flag="is_superuser")
    """

    def __init__(
        self,
        model: type[Any],
        pk_field: str,
        flags: Sequence[str],
        *,
        admin_flag: str | None = None,
        schema: PermissionSchema | None = None,
    ) -> None:
        """Validate the model, its primary key and the flag columns.

        Raises:
            ConfigurationError: if `model` is not mapped, `pk_field` is not its
                single-column primary key, or a flag is not a column of it.

        """
        candidate = cast("object", model)
        mapper: object = (
            sa_inspect(candidate, raiseerr=False) if isinstance(candidate, type) else None
        )
        if not isinstance(mapper, Mapper):
            msg = f"FlagAccountGuard: {model!r} is not a mapped SQLAlchemy class."
            raise ConfigurationError(msg)
        keys = [mapper.get_property_by_column(column).key for column in mapper.primary_key]
        if keys != [pk_field]:
            msg = f"FlagAccountGuard: {pk_field!r} is not the primary key of {model.__name__}."
            raise ConfigurationError(msg)
        columns = set(mapper.columns.keys())
        for flag in (*flags, *([admin_flag] if admin_flag else [])):
            if flag not in columns:
                msg = f"FlagAccountGuard: {flag!r} is not a column of {model.__name__}."
                raise ConfigurationError(msg)
        self._model: type[Any] = model
        self._mapper: Mapper[Any] = mapper
        self._pk_field: str = pk_field
        self._flags: tuple[str, ...] = tuple(flags)
        self._admin_flag: str | None = admin_flag
        self._schema: PermissionSchema | None = schema

    def _active_admin(self) -> ColumnElement[bool]:
        """Return the SQL condition for rows that may sign in (every flag is true)."""
        conditions = [getattr(self._model, flag).is_(True) for flag in self._flags]
        return and_(true(), *conditions)

    def guards(self, model: type[Any]) -> bool:
        """Return True for the user model and mapped subclasses of it."""
        mapper = sa_inspect(model, raiseerr=False)
        return isinstance(mapper, Mapper) and mapper.isa(self._mapper)

    def protected_fields(self, model: type[Any]) -> tuple[str, ...]:
        """Return the sign-in flags: an admin cannot change them on their own record."""
        del model
        return self._flags

    def admin_flag(self, model: type[Any]) -> str | None:
        """Return the superuser-like flag for guarded models."""
        return self._admin_flag if self.guards(model) else None

    def permission_schema(self) -> PermissionSchema | None:
        """Return the permission schema given at construction, if any."""
        return self._schema

    def check_model(self, model: type[Any]) -> None:
        """Refuse other mappings of the user table: their writes could not be checked."""
        mapper = sa_inspect(model, raiseerr=False)
        if not isinstance(mapper, Mapper) or mapper.isa(self._mapper):
            return
        if set(mapper.tables) & set(self._mapper.tables):
            msg = (
                f"{model.__name__} maps a table of {self._model.__name__}, the model that "
                f"holds the admin accounts. Register {self._model.__name__} (or a subclass "
                "of it) instead, so that writes to admin accounts are checked (ADR-0009)."
            )
            raise ConfigurationError(msg)

    async def before_write(
        self, session: AsyncSession, user: AuthenticatedUser, intent: WriteIntent
    ) -> PostWriteCheck | None:
        """Refuse self-lockout; check the last active admin after the write (ADR-0009)."""
        obj = intent.obj
        if intent.action == "create":
            return None  # a new account never removes an admin
        own = str(getattr(obj, self._pk_field)) == user.id
        if intent.action == "delete":
            if own:
                raise WriteRefused("self_lockout", "You cannot delete your own account.")
            may_remove_admin = True
        elif intent.action == "update":
            sent = [flag for flag in self._flags if flag in intent.changes]
            if own and any(intent.changes[flag] != getattr(obj, flag) for flag in sent):
                raise WriteRefused(
                    "self_lockout", "You cannot change your own active or admin status."
                )
            may_remove_admin = any(intent.changes[flag] is not True for flag in sent)
        else:  # an action this guard does not know: refuse (fail closed)
            assert_never(intent.action)
        # Decided from the request, never from `obj`: it was loaded before any lock,
        # so a concurrent write may already have made it an active admin.
        if not may_remove_admin:
            return None
        pk = getattr(self._model, self._pk_field)
        # Lock every active admin in a fixed order before writing, so concurrent
        # removals serialize instead of each seeing the other admin still there.
        # (FOR UPDATE is omitted on SQLite, where the flush takes the write lock.)
        await session.execute(select(pk).where(self._active_admin()).order_by(pk).with_for_update())

        async def check_remaining() -> None:
            # A locking read sees the latest committed rows. A plain read would use
            # the transaction's earlier snapshot under MySQL REPEATABLE READ.
            statement = select(pk).where(self._active_admin()).limit(1).with_for_update()
            if (await session.scalars(statement)).first() is None:
                raise WriteRefused("last_admin", "At least one active admin must remain.")

        return check_remaining
