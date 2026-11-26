"""`DatabaseAuthBackend`: sign-in, permissions and passwords for `AuthModels`."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import String, cast, literal, null, select, union, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from faststudio import (
    ALL,
    AuthenticatedUser,
    BackendCapabilities,
    ConfigurationError,
    FlagAccountGuard,
)
from faststudio.auth.capabilities import AuditedAccount, Permissions, PermissionSchema
from faststudio.auth.passwords import (
    dummy_verify_async,
    hash_password_async,
    is_password_hash,
    prepare_dummy_hash,
    verify_password_async,
)
from faststudio.auth.session import new_session_token
from faststudio.auth.validators import DEFAULT_VALIDATORS, PasswordValidator
from faststudio.contrib.auth.admins import SECRET_FIELDS, group_admin, permission_admin, user_admin
from faststudio.contrib.auth.models import (
    AuthModels,
    UserMixin,
    normalize_username,
)

if TYPE_CHECKING:
    from faststudio import Admin

__all__ = ["DatabaseAuthBackend"]

logger = logging.getLogger("faststudio.auth")

#: Accounts whose superuser status is remembered between get_user and resolve.
_SUPERUSER_CACHE = 1024


class DatabaseAuthBackend:
    """Authenticate admin staff against `AuthModels` and grant their permissions.

    - Any **active** user may sign in; superusers hold every permission,
      other users the permissions of their account and groups.
    - New users have an unusable password until one is set (password
      endpoints, or the CLI).
    - With ``register_admins=True`` (default) the users, groups and
      permissions admins are registered automatically; pass ``False`` to
      register your own subclasses (see `faststudio.contrib.auth.admins`).

    These are staff accounts: never store your application's end users here.
    """

    def __init__(
        self,
        models: AuthModels,
        *,
        password_validators: Sequence[PasswordValidator] = DEFAULT_VALIDATORS,
        register_admins: bool = True,
    ) -> None:
        """Wire the capabilities; raises `ConfigurationError` on bad arguments."""
        candidate: object = models  # untyped callers
        if not isinstance(candidate, AuthModels):
            msg = "DatabaseAuthBackend: models must come from AuthModels(Base)."
            raise ConfigurationError(msg)
        raw: object = password_validators
        validators = tuple(password_validators)
        if isinstance(raw, str) or not all(isinstance(v, PasswordValidator) for v in validators):
            msg = "DatabaseAuthBackend: password_validators must be PasswordValidator instances."
            raise ConfigurationError(msg)
        self.models = models
        self._user = models.user
        self.password_validators: Sequence[PasswordValidator] = validators
        # (id, auth_version) -> is_superuser, filled by get_user: resolve() can then
        # answer ALL for superusers without a query. auth_version covers the flag.
        self._superusers: OrderedDict[tuple[str, str], bool] = OrderedDict()
        prepare_dummy_hash()
        self._capabilities = BackendCapabilities(
            account_guard=FlagAccountGuard(
                models.user,
                "id",
                ("is_active", "is_superuser"),
                admin_flag="is_superuser",
                secret_fields=SECRET_FIELDS,
            ),
            permissions=self,
            permission_schema=PermissionSchema(
                user_model=models.user,
                permission_model=models.permission,
                codename_field="codename",
                name_field="name",
                user_permissions="permissions",
                group_model=models.group,
                user_groups="groups",
                group_permissions="permissions",
                group_users="users",
                permission_groups="groups",
                permission_users="users",
            ),
            accounts=self,
            username_audit=self,
            session_revocation=self,
            password_endpoints=True,
            register_admins=self._register if register_admins else None,
        )

    @property
    def faststudio_capabilities(self) -> BackendCapabilities:
        """Account guard, permissions, escalation schema, passwords and admins."""
        return self._capabilities

    def _register(self, admin: Admin) -> None:
        for factory in (user_admin, group_admin, permission_admin):
            admin.register(factory(self.models))

    # ------------------------------------------------------------- AuthBackend

    @staticmethod
    def _maker(request: Request) -> async_sessionmaker[AsyncSession]:
        context = getattr(request.app.state, "faststudio", None)
        if context is None:
            msg = "DatabaseAuthBackend can only be used by a mounted faststudio.Admin."
            raise ConfigurationError(msg)
        maker: async_sessionmaker[AsyncSession] = context.session_maker
        return maker

    def _authenticated(self, row: UserMixin) -> AuthenticatedUser:
        state = f"{row.password_hash}|{row.is_active}|{row.is_superuser}|{row.session_token}"
        user = AuthenticatedUser(
            id=str(row.id),
            username=row.username,
            auth_version=hashlib.sha256(state.encode()).hexdigest()[:32],
        )
        self._superusers[(user.id, user.auth_version)] = row.is_superuser
        self._superusers.move_to_end((user.id, user.auth_version))
        while len(self._superusers) > _SUPERUSER_CACHE:
            self._superusers.popitem(last=False)
        return user

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        """Verify the password of an active account (constant time on failure)."""
        statement = select(self._user).where(
            self._user.username_normalized == normalize_username(username)
        )
        async with self._maker(request)() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            stored = row.password_hash if row is not None else None
            if row is None or stored is None or not is_password_hash(stored):
                await dummy_verify_async(password)
                return None
            if not await verify_password_async(stored, password) or not row.is_active:
                return None
            user = self._authenticated(row)
            try:  # best effort: a busy database must not turn a valid sign-in into an error
                await session.execute(
                    update(self._user)
                    .where(self._user.id == row.id)
                    .values(last_login=datetime.now(UTC))
                )
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.warning("Could not record last_login (%s)", type(exc).__name__)
            return user

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        """Reload the account for a session; None if gone or inactive (one query)."""
        if not (user_id.isascii() and user_id.isdecimal()):
            return None
        async with self._maker(request)() as session:
            row = await session.get(self._user, int(user_id))
            if row is None or not row.is_active:
                return None
            return self._authenticated(row)

    # ------------------------------------------------------------- PermissionBackend

    async def resolve(self, session: AsyncSession, user: AuthenticatedUser) -> Permissions:
        """`ALL` for superusers (no query), else the account's and groups' codenames."""
        if self._superusers.get((user.id, user.auth_version)) is True:
            return ALL
        key = int(user.id)
        return (await self.resolve_accounts(session, [key])).get(key, frozenset())

    async def resolve_accounts(
        self, session: AsyncSession, keys: Sequence[object]
    ) -> Mapping[object, Permissions]:
        """One query: an entry for every existing account in `keys`."""
        user, permission = self._user, self.models.permission
        user_permissions, user_groups = self.models.user_permissions, self.models.user_groups
        group_permissions = self.models.group_permissions
        uid, codename = "uid", "codename"
        direct = (
            select(user_permissions.c.user_id.label(uid), permission.codename.label(codename))
            .join(permission, permission.id == user_permissions.c.permission_id)
            .where(user_permissions.c.user_id.in_(keys))
        )
        grouped = (
            select(user_groups.c.user_id.label(uid), permission.codename.label(codename))
            .join(group_permissions, group_permissions.c.group_id == user_groups.c.group_id)
            .join(permission, permission.id == group_permissions.c.permission_id)
            .where(user_groups.c.user_id.in_(keys))
        )
        superusers = select(user.id.label(uid), cast(null(), String(100)).label(codename)).where(
            user.id.in_(keys), user.is_superuser.is_(True)
        )
        existing = select(user.id.label(uid), literal("", String(100)).label(codename)).where(
            user.id.in_(keys)
        )
        rows = (await session.execute(union(direct, grouped, superusers, existing))).all()
        found: dict[Any, set[str]] = {}
        result: dict[object, Permissions] = {}
        for account, code in rows:
            if code is None:
                result[account] = ALL
            else:
                codes = found.setdefault(account, set())
                if code:
                    codes.add(code)
        for account, codes in found.items():
            result.setdefault(account, frozenset(codes))
        return result

    # ------------------------------------------------------------- AccountManager

    async def _row(self, session: AsyncSession, account_id: str) -> UserMixin | None:
        return (
            await session.get(self._user, int(account_id))
            if account_id.isascii() and account_id.isdecimal()
            else None
        )

    async def user_inputs(self, session: AsyncSession, account_id: str) -> Sequence[str]:
        """Return the username and email of the account."""
        row = await self._row(session, account_id)
        return [v for v in (row.username, row.email) if v] if row is not None else ()

    async def check_password(self, session: AsyncSession, account_id: str, password: str) -> bool:
        """Verify `password`; missing accounts and unusable hashes take the same time."""
        row = await self._row(session, account_id)
        if row is None or not is_password_hash(row.password_hash):
            return await dummy_verify_async(password)
        return await verify_password_async(row.password_hash, password)

    async def set_password(self, session: AsyncSession, account_id: str, password: str) -> None:
        """Hash and store `password` (the caller commits); `LookupError` if missing."""
        row = await self._row(session, account_id)
        if row is None:
            raise LookupError(account_id)
        row.password_hash = await hash_password_async(password)

    async def find_account(self, session: AsyncSession, username: str) -> str | None:
        """Return the id of the account signing in as `username` (normalized match)."""
        statement = select(self._user.id).where(
            self._user.username_normalized == normalize_username(username)
        )
        found = (await session.execute(statement)).scalar_one_or_none()
        return None if found is None else str(found)

    def required_fields(self) -> Sequence[str]:
        """Return nothing: every other column has a default."""
        return ()

    async def create_admin(
        self, session: AsyncSession, *, username: str, password: str, fields: Mapping[str, str]
    ) -> str:
        """Create an active superuser through the ORM and return its id.

        Raises:
            ValueError: for fields other than ``email``.

        """
        unknown = sorted(set(fields) - {"email"})
        if unknown:
            msg = f"Unknown field(s): {', '.join(unknown)} (only email can be set)."
            raise ValueError(msg)
        row = self._user(
            username=username,
            password_hash=await hash_password_async(password),
            is_active=True,
            is_superuser=True,
            email=fields.get("email", ""),
        )
        session.add(row)
        await session.flush()
        return str(row.id)

    # ------------------------------------------------------------- SessionRevocation

    async def rotate_session_token(self, session: AsyncSession, account_id: str) -> None:
        """Store a fresh session token, ending every session (the caller commits).

        Raises:
            LookupError: if the account does not exist.

        """
        row = await self._row(session, account_id)
        if row is None:
            raise LookupError(account_id)
        row.session_token = new_session_token()

    # ------------------------------------------------------------- UsernameAudit

    async def audit(self, session: AsyncSession) -> Sequence[AuditedAccount]:
        """Return every account with its stored and expected normalized username."""
        statement = select(self._user.id, self._user.username, self._user.username_normalized)
        return [
            AuditedAccount(
                account_id=str(pk),
                username=username,
                stored=stored,
                expected=normalize_username(username),
            )
            for pk, username, stored in (await session.execute(statement)).all()
        ]

    async def fix(self, session: AsyncSession, account_ids: Sequence[str]) -> None:
        """Re-derive the normalized username of `account_ids` through the ORM."""
        for account_id in account_ids:
            row = await self._row(session, account_id)
            if row is not None:
                row.username_normalized = normalize_username(row.username)
        await session.flush()
