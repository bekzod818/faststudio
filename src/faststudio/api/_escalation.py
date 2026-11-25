"""Escalation rules: nobody grants more than they hold (ADR-0011 §6, A2; threat model T9).

Enforced by core on create, update and delete, before the account guard, for
every admin who does not hold `ALL`:

- only `ALL` may change the superuser-like flag, or edit or delete an account
  that holds `ALL`;
- the codenames a write could give anyone (user or group grants, group
  membership, from either side of the relationship, or renaming a
  permission) must all be held by the actor.

The check uses a conservative closed form with a fixed number of queries,
computed from the write's intent in its transaction, after locking the
affected group and user rows in primary-key order. Removals never escalate.
The backend only declares where its data lives (`PermissionSchema`) and
resolves accounts; the rules themselves live here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Column, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper

from faststudio.api._many import bind_to
from faststudio.api.errors import ApiError
from faststudio.auth.capabilities import (
    AllPermissions,
    BackendCapabilities,
    PermissionBackend,
    Permissions,
    PermissionSchema,
    covers,
    holds,
)
from faststudio.auth.guard import WriteIntent
from faststudio.exceptions import ConfigurationError
from faststudio.introspection._many import ManyToManyLink, NotPlainError, plain_many_to_many
from faststudio.query._many import chunks
from faststudio.registry import RegisteredModel

Side = Literal["user", "group", "permission"]
Kind = Literal[
    "user_permissions",
    "user_groups",
    "group_permissions",
    "group_users",
    "permission_groups",
    "permission_users",
]

#: Each declared relationship: the side declaring it and the side it targets.
_KINDS: dict[Kind, tuple[Side, Side]] = {
    "user_permissions": ("user", "permission"),
    "user_groups": ("user", "group"),
    "group_permissions": ("group", "permission"),
    "group_users": ("group", "user"),
    "permission_groups": ("permission", "group"),
    "permission_users": ("permission", "user"),
}


def _forbidden() -> ApiError:
    return ApiError(403, "forbidden")


@dataclass(frozen=True, slots=True)
class EscalationRules:
    """A validated `PermissionSchema`: models, links and codename column."""

    models: Mapping[Side, type[Any]]
    #: Relationship name on its side's model -> (kind, link).
    links: Mapping[Side, Mapping[str, tuple[Kind, ManyToManyLink]]]
    codename: Column[Any]
    #: Association tables of the declared relationships (never registrable).
    tables: frozenset[Any] = field(default_factory=frozenset)

    @classmethod
    def from_capabilities(cls, capabilities: BackendCapabilities) -> EscalationRules | None:
        """Validate the guard's `PermissionSchema` at startup (None without one).

        Raises:
            ConfigurationError: on a relationship that is missing, not a plain
                many-to-many or not between the declared models, an unknown
                codename column, or a schema without a permission backend.

        """
        guard = capabilities.account_guard
        schema: object = guard.permission_schema() if guard is not None else None
        if schema is None:
            return None
        if not isinstance(schema, PermissionSchema):  # untyped backends
            msg = "AccountGuard.permission_schema() must return a PermissionSchema or None."
            raise ConfigurationError(msg)
        if capabilities.permissions is None:
            msg = "A PermissionSchema needs BackendCapabilities.permissions to resolve accounts."
            raise ConfigurationError(msg)
        models: dict[Side, type[Any]] = {
            "user": schema.user_model,
            "permission": schema.permission_model,
        }
        if schema.group_model is not None:
            models["group"] = schema.group_model
        links: dict[Side, dict[str, tuple[Kind, ManyToManyLink]]] = {side: {} for side in models}
        tables = set()
        for kind, (side, target) in _KINDS.items():
            name: str | None = getattr(schema, kind)
            if name is None:
                continue
            if side not in models or target not in models:
                msg = f"PermissionSchema.{kind} needs a group_model."
                raise ConfigurationError(msg)
            link = _link(models[side], name, kind, models[target])
            links[side][name] = (kind, link)
            tables.add(link.secondary)
        if (
            "group" in models
            and schema.group_permissions is None
            and schema.permission_groups is None
        ):
            # Without it core could not tell what joining a group grants.
            msg = (
                "PermissionSchema with a group_model must name group_permissions or "
                "permission_groups (read to compute what a group grants)."
            )
            raise ConfigurationError(msg)
        codename = _mapper(models["permission"]).columns.get(schema.codename_field)
        if codename is None:
            msg = (
                f"PermissionSchema.codename_field {schema.codename_field!r} is not a column "
                f"of {models['permission'].__name__}."
            )
            raise ConfigurationError(msg)
        return cls(models=models, links=links, codename=codename, tables=frozenset(tables))

    def side_of(self, model: type[Any]) -> Side | None:
        """Return which side `model` is (a mapped subclass counts)."""
        mapper = sa_inspect(model)
        for side, side_model in self.models.items():
            if mapper.isa(_mapper(side_model)):
                return side
        return None

    def check_model(self, registered: RegisteredModel) -> None:
        """Refuse registrations that would write permissions past the rules.

        Raises:
            ConfigurationError: for a model mapping a declared association
                table, or an opted-in many-to-many field over such a table
                that is not a declared side.

        """
        mapper = sa_inspect(registered.model)
        if set(mapper.tables) & self.tables:
            msg = (
                f"{registered.model.__name__} maps a permission association table; writes "
                "to it would bypass the escalation rules (ADR-0011)."
            )
            raise ConfigurationError(msg)
        side = self.side_of(registered.model)
        declared = self.links.get(side, {}) if side is not None else {}
        for name, many in registered.many_to_many.items():
            if many.readonly or many.link.secondary not in self.tables or name in declared:
                continue
            msg = (
                f"{registered.admin_class.__name__}: many_to_many {name!r} writes a permission "
                "association table but is not declared in the backend's PermissionSchema; "
                "make it readonly or declare it (ADR-0011)."
            )
            raise ConfigurationError(msg)

    # ------------------------------------------------------------------ queries

    async def _lock(self, session: AsyncSession, side: Side, keys: Iterable[object]) -> None:
        """Lock rows of one side in primary-key order (no-op on SQLite)."""
        model = self.models[side]
        pk = _mapper(model).primary_key[0]
        ordered = sorted(set(keys), key=repr)
        for chunk in chunks(ordered):
            await session.execute(
                select(pk).where(pk.in_(chunk)).order_by(pk).with_for_update(),
                bind_arguments=bind_to(model),
            )

    async def _codenames(self, session: AsyncSession, keys: Iterable[object]) -> set[str]:
        """Codenames of the permission rows `keys`."""
        model = self.models["permission"]
        pk = _mapper(model).primary_key[0]
        found: set[str] = set()
        for chunk in chunks(sorted(set(keys), key=repr)):
            rows = await session.scalars(
                select(self.codename).where(pk.in_(chunk)), bind_arguments=bind_to(model)
            )
            found.update(rows)
        return found

    async def _group_codenames(self, session: AsyncSession, groups: Iterable[object]) -> set[str]:
        """Codenames granted by the groups `groups` (their current permissions)."""
        found: set[str] = set()
        group_links = self.links.get("group", {})
        link = next((ln for kind, ln in group_links.values() if kind == "group_permissions"), None)
        if link is None:
            link = self._reverse("permission", "permission_groups")
            if link is None:
                return found  # pragma: no cover - from_capabilities requires one of the two
            group_fk, permission_fk = link.remote_fk, link.local_fk
        else:
            group_fk, permission_fk = link.local_fk, link.remote_fk
        permission = self.models["permission"]
        pk = _mapper(permission).primary_key[0]
        for chunk in chunks(sorted(set(groups), key=repr)):
            rows = await session.scalars(
                select(self.codename)
                .join(link.secondary, permission_fk == pk)
                .where(group_fk.in_(chunk)),
                bind_arguments=bind_to(permission),
            )
            found.update(rows)
        return found

    def _reverse(self, side: Side, kind: Kind) -> ManyToManyLink | None:
        return next((ln for k, ln in self.links.get(side, {}).values() if k == kind), None)

    # ------------------------------------------------------------------ the rule

    async def gains(
        self,
        session: AsyncSession,
        backend: PermissionBackend,
        registered: RegisteredModel,
        intent: WriteIntent,
        added: Mapping[str, Sequence[object]],
    ) -> set[str]:
        """Return every codename this write could give anyone (conservative).

        `added` maps each declared field the write changes to the keys it adds.
        """
        side = self.side_of(registered.model)
        if side is None or intent.action == "delete":
            return set()  # removals never escalate
        declared = self.links.get(side, {})
        by_kind: dict[Kind, list[object]] = {}
        for name, keys in added.items():
            if name in declared and keys:
                by_kind[declared[name][0]] = list(keys)
        pk = None if intent.action == "create" else getattr(intent.obj, registered.pk_field)
        gains: set[str] = set()

        if side == "permission":
            current = None if pk is None else getattr(intent.obj, self.codename.key)
            new = intent.changes.get(self.codename.key, current)
            renamed = pk is not None and new != current
            if renamed and isinstance(new, str):
                gains.add(new)  # everyone holding this permission now holds `new`
            code = {new} if isinstance(new, str) else set()
            if "permission_groups" in by_kind:
                await self._lock(session, "group", by_kind["permission_groups"])
                gains |= code
            users = by_kind.get("permission_users", [])
            if users:
                await self._lock(session, "user", users)
                gains |= await _new_for(session, backend, users, code)
            return gains

        if side == "group":
            group_keys = [*([] if pk is None else [pk])]
            added_codes = await self._codenames(session, by_kind.get("group_permissions", []))
            gains |= added_codes
            users = by_kind.get("group_users", [])
            if users:
                await self._lock(session, "group", group_keys)
                await self._lock(session, "user", users)
                held = await self._group_codenames(session, group_keys) | added_codes
                gains |= await _new_for(session, backend, users, held)
            return gains

        # side == "user": what this one user would gain.
        groups = by_kind.get("user_groups", [])
        permissions = by_kind.get("user_permissions", [])
        if not groups and not permissions:
            return gains
        await self._lock(session, "group", groups)
        if pk is not None:
            await self._lock(session, "user", [pk])
        gained = await self._group_codenames(session, groups) | await self._codenames(
            session, permissions
        )
        if pk is None:
            return gained  # a new account holds nothing yet
        return await _new_for(session, backend, [pk], gained)


async def _new_for(
    session: AsyncSession, backend: PermissionBackend, users: Sequence[object], codes: set[str]
) -> set[str]:
    """Codenames in `codes` that at least one of `users` does not hold yet."""
    if not codes:
        return set()
    before = await backend.resolve_accounts(session, users)
    gained: set[str] = set()
    for user in users:
        held: Permissions = before.get(user, frozenset())
        gained |= {code for code in codes if not holds(held, code)}
    return gained


def _mapper(model: type[Any]) -> Mapper[Any]:
    mapper = sa_inspect(model, raiseerr=False)
    if not isinstance(mapper, Mapper):
        msg = f"PermissionSchema: {model!r} is not a mapped SQLAlchemy class."
        raise ConfigurationError(msg)
    return mapper


def _link(model: type[Any], name: str, kind: str, target: type[Any]) -> ManyToManyLink:
    relationship = _mapper(model).relationships.get(name)
    if relationship is None:
        msg = f"PermissionSchema.{kind}: {model.__name__} has no relationship {name!r}."
        raise ConfigurationError(msg)
    try:
        link = plain_many_to_many(relationship)
    except NotPlainError as exc:
        msg = f"PermissionSchema.{kind}: {model.__name__}.{name} is not usable: {exc.reason}."
        raise ConfigurationError(msg) from None
    if link.target_model is not target:
        msg = (
            f"PermissionSchema.{kind}: {model.__name__}.{name} targets "
            f"{link.target_model.__name__}, not {target.__name__}."
        )
        raise ConfigurationError(msg)
    return link


async def check_escalation(
    session: AsyncSession,
    *,
    capabilities: BackendCapabilities,
    rules: EscalationRules | None,
    actor: Permissions,
    registered: RegisteredModel,
    intent: WriteIntent,
    added: Mapping[str, Sequence[object]],
) -> None:
    """Raise `403 forbidden` if the write would give anyone more than the actor holds."""
    backend = capabilities.permissions
    if isinstance(actor, AllPermissions) or backend is None:
        return  # holds everything (always so without a permission backend)
    guard = capabilities.account_guard
    if guard is not None and guard.guards(registered.model):
        flag = guard.admin_flag(registered.model)
        if flag is not None and flag in intent.changes:
            value = intent.changes[flag]
            if (intent.action == "create" and value is True) or (
                intent.action == "update" and value != getattr(intent.obj, flag)
            ):
                raise _forbidden()
        if intent.action != "create":
            pk = getattr(intent.obj, registered.pk_field)
            target = (await backend.resolve_accounts(session, [pk])).get(pk)
            if isinstance(target, AllPermissions):
                raise _forbidden()
    if rules is None:
        return
    gains = await rules.gains(session, backend, registered, intent, added)
    if not covers(actor, frozenset(gains)):
        raise _forbidden()
