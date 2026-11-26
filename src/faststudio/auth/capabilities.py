"""Optional capabilities of an auth backend (ADR-0011).

A backend opts in by defining ``faststudio_capabilities`` (an attribute or a
property) that returns a :class:`BackendCapabilities`. Nothing else on a
backend is ever inspected. Without it, FastStudio behaves as in v0.1: every
signed-in admin may do everything the ``ModelAdmin`` flags allow.

Capability methods receive an ``AsyncSession`` and never a ``Request``, so
the CLI can call them too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, final, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.auth.backend import AuthenticatedUser

if TYPE_CHECKING:
    from faststudio.admin import Admin
    from faststudio.auth.guard import AccountGuard
    from faststudio.auth.validators import PasswordValidator

__all__ = [
    "ALL",
    "AccountManager",
    "AllPermissions",
    "AuditedAccount",
    "BackendCapabilities",
    "PermissionBackend",
    "PermissionSchema",
    "Permissions",
    "SessionRevocation",
    "UsernameAudit",
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

        `keys` are native primary keys of the model the account guard covers
        (the user model), unlike `AccountManager`, which takes string ids.
        Used by the escalation rules to check the accounts a write affects,
        including "the target holds `ALL`". Return an entry (possibly an
        empty frozenset) for **every requested key that exists**,
        keyed by the same values: an account left out is treated as possibly
        holding `ALL` when it is the target of a write (refused), and as
        holding nothing when it would gain permissions.
        """
        ...


@runtime_checkable
class AccountManager(Protocol):
    """Capability: manage the passwords of admin accounts (ADR-0011, ADR-0013).

    Used by the password endpoints and the CLI. `account_id` identifies a
    row of the model the `account_guard` covers, as the same string as
    `AuthenticatedUser.id` (unlike `PermissionBackend.resolve_accounts`,
    which takes native primary keys); an id that does not parse or match is
    a missing account. Methods run in the
    caller's transaction; the caller commits.
    """

    @property
    def password_validators(self) -> Sequence[PasswordValidator]:
        """Checked, after FastStudio's hard limits, for every new password."""
        ...

    async def user_inputs(self, session: AsyncSession, account_id: str) -> Sequence[str]:
        """Return the account's name, email and similar values (for similarity checks)."""
        ...

    async def check_password(self, session: AsyncSession, account_id: str, password: str) -> bool:
        """Return True if `password` is the account's password.

        Take the same time whether or not the account exists or has a usable
        password (verify against a dummy hash), so the answer reveals nothing.
        """
        ...

    async def set_password(self, session: AsyncSession, account_id: str, password: str) -> None:
        """Store `password` (hashed with `faststudio.hash_password`) for the account.

        Raise `LookupError` if the account does not exist.
        """
        ...

    async def find_account(self, session: AsyncSession, username: str) -> str | None:
        """Return the `account_id` of the account signing in as `username`, or None.

        Match the way sign-in does (e.g. normalized). Return None when no
        single account matches.
        """
        ...

    def required_fields(self) -> Sequence[str]:
        """Return text fields `create_admin` needs besides username and password."""
        ...

    async def create_admin(
        self, session: AsyncSession, *, username: str, password: str, fields: Mapping[str, str]
    ) -> str:
        """Create an account with every permission and return its `account_id`.

        `password` was validated by the caller; hash it. Use the ORM, so
        model-level hooks run. The caller commits.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditedAccount:
    """One account as `UsernameAudit` sees it."""

    account_id: str
    username: str
    #: The stored sign-in key.
    stored: str
    #: What it should be for `username`.
    expected: str


@runtime_checkable
class UsernameAudit(Protocol):
    """Capability: find and repair drift of a stored, normalized sign-in key.

    Used by ``faststudio checkusers``. Backends that sign in by the
    username itself need not provide it.
    """

    async def audit(self, session: AsyncSession) -> Sequence[AuditedAccount]:
        """Return every account with its stored and expected sign-in key.

        Every account, unpaged: fine for staff-account tables.
        """
        ...

    async def fix(self, session: AsyncSession, account_ids: Sequence[str]) -> None:
        """Set the stored key to the expected one for `account_ids` (caller commits).

        Collisions are the caller's to avoid (``checkusers`` skips them); the
        key's unique index rejects any that remain.
        """
        ...


@runtime_checkable
class SessionRevocation(Protocol):
    """Capability: end every session of an account ("sign out everywhere", ADR-0013).

    Sessions are stateless; an account's sessions end when its
    ``auth_version`` changes. Implementations rotate a random per-account
    token that is part of the ``auth_version``.
    """

    async def rotate_session_token(self, session: AsyncSession, account_id: str) -> None:
        """Replace the account's session token (the caller commits).

        Raises:
            LookupError: if the account does not exist.

        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
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
    #: Column holding a human-readable name, written by ``syncpermissions``.
    name_field: str | None = None
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


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendCapabilities:
    """The capabilities an auth backend provides; every field is optional.

    Attributes:
        account_guard: Protects the accounts that can sign in (ADR-0009).
        permissions: Per-user permissions. Without it every admin holds `ALL`.
        permission_schema: Where users, groups and permissions are stored, so
            core can enforce the escalation rules on writes to them. Needs
            `permissions`, and an `account_guard` that covers its user model.
        accounts: Sets and checks account passwords (CLI, password endpoints).
        register_admins: Called with the `Admin` at the end of its
            construction, to register the backend's own models (e.g. users
            and groups of `faststudio.contrib.auth`).
        username_audit: Finds and repairs a drifted sign-in key
            (``faststudio checkusers``).
        session_revocation: Ends every session of an account, offered to
            signed-in admins as "Sign out everywhere".
        password_endpoints: Offer the HTTP password endpoints (needs
            `accounts` and an `account_guard`). Off by default: with
            `ModelUserBackend` every admin holds `ALL`, so any admin could
            reset another admin's password.

    New capabilities arrive as new optional fields (ADR-0011): the protocols
    above are frozen once released.

    """

    account_guard: AccountGuard | None = None
    permissions: PermissionBackend | None = None
    permission_schema: PermissionSchema | None = None
    accounts: AccountManager | None = None
    username_audit: UsernameAudit | None = None
    session_revocation: SessionRevocation | None = None
    password_endpoints: bool = False
    register_admins: Callable[[Admin], None] | None = None
