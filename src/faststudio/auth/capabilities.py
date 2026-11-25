"""Optional capabilities of an auth backend (ADR-0011).

A backend opts in by defining ``faststudio_capabilities`` (an attribute or a
property) that returns a :class:`BackendCapabilities`. Nothing else on a
backend is ever inspected. Without it, FastStudio behaves as in v0.1: every
signed-in admin may do everything the ``ModelAdmin`` flags allow.

Capability methods receive an ``AsyncSession`` and never a ``Request``, so
the CLI can call them too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, final, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.auth.backend import AuthenticatedUser

if TYPE_CHECKING:
    from faststudio.auth.guard import AccountGuard

__all__ = [
    "ALL",
    "AllPermissions",
    "BackendCapabilities",
    "PermissionBackend",
    "PermissionSchema",
    "Permissions",
]

#: The four model actions. Codenames are ``"<identity>.<action>"``.
ACTIONS: Final = ("view", "create", "edit", "delete")


@final
class AllPermissions:
    """Every permission, including codenames that do not exist yet (superusers)."""

    _instance: AllPermissions | None = None

    def __new__(cls) -> AllPermissions:
        """Return the single instance, so `perms is ALL` is the test."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        """Show as ``ALL``."""
        return "ALL"

    def __reduce__(self) -> str:
        """Unpickle to the same singleton."""
        return "ALL"


ALL: Final = AllPermissions()

#: What a user may do: `ALL`, or the codenames they hold.
Permissions = AllPermissions | frozenset[str]


def holds(perms: Permissions, codename: str) -> bool:
    """Return True if `perms` grants `codename`; `<identity>.edit` also grants view."""
    if isinstance(perms, AllPermissions):
        return True
    if codename in perms:
        return True
    identity, _, action = codename.rpartition(".")
    return action == "view" and f"{identity}.edit" in perms


def covers(perms: Permissions, codenames: frozenset[str]) -> bool:
    """Return True if `perms` grants every codename in `codenames`."""
    return all(holds(perms, codename) for codename in codenames)


@runtime_checkable
class PermissionBackend(Protocol):
    """Capability: per-user permissions (ADR-0011 §3).

    Both methods are ``async``. Superuser handling is the backend's: return
    `ALL` for users who may do everything.
    """

    async def resolve(self, session: AsyncSession, user: AuthenticatedUser) -> Permissions:
        """Return the signed-in user's permissions (called once per request)."""
        ...

    async def resolve_accounts(
        self, session: AsyncSession, keys: Sequence[object]
    ) -> Mapping[object, Permissions]:
        """Return the current permissions of the accounts with primary keys `keys`.

        Used by the escalation rules to check the accounts a write affects.
        Missing keys may be left out (they hold nothing).
        """
        ...


@dataclass(frozen=True, slots=True)
class PermissionSchema:
    """Where a backend stores users, groups and permissions (ADR-0011 §6).

    FastStudio uses it to enforce the escalation rules on writes through the
    admin, whichever side of a relationship the write comes from. Every
    relationship named here must be a plain many-to-many (ADR-0010); give the
    names of the sides that are writable in the admin, ``None`` for the
    others. Group fields may be ``None`` when the backend has no groups.
    """

    user_model: type[Any]
    permission_model: type[Any]
    #: Column of `permission_model` holding the codename.
    codename_field: str
    #: ``user.permissions`` (direct grants).
    user_permissions: str | None
    group_model: type[Any] | None = None
    #: ``user.groups``.
    user_groups: str | None = None
    #: ``group.permissions``.
    group_permissions: str | None = None
    #: Reverse sides, if they are writable: ``group.users``,
    #: ``permission.groups`` and ``permission.users``.
    group_users: str | None = None
    permission_groups: str | None = None
    permission_users: str | None = None


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """The capabilities an auth backend provides; every field is optional.

    Attributes:
        account_guard: Protects the accounts that can sign in (ADR-0009).
        permissions: Per-user permissions. Without it every admin holds `ALL`.

    """

    account_guard: AccountGuard | None = None
    permissions: PermissionBackend | None = None
