"""Account-safety guard: an optional capability of auth backends (ADR-0009, private).

The write API asks the backend whether a write to the model that stores its
admins would lock someone out, before the write is flushed, and again after
the flush in the same transaction. A backend that does not implement
`AccountGuard` is never consulted.

This module stays private in 0.1.x; ADR-0009 promotes it with the v0.2 auth
capabilities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.auth.backend import AuthenticatedUser

WriteAction = Literal["update", "delete"]
RefusalCode = Literal["self_lockout", "last_admin"]

#: Runs after the write is flushed, before commit; raises `WriteRefused` to undo it.
PostWriteCheck = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WriteIntent:
    """A pending write: the loaded object and the validated changes (empty for deletes)."""

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
    """Backend capability: protect the accounts that can sign in to the admin."""

    def guards(self, model: type[Any]) -> bool:
        """Return True if writes to `model` must be checked."""
        ...

    def check_model(self, model: type[Any]) -> None:
        """Raise `ConfigurationError` at `register()` if `model` would bypass the guard.

        For example another class mapped to the table that holds the accounts.
        """
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
