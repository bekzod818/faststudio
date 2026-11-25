"""Create permission rows for the registered models (ADR-0012 §5; private).

Shared by ``faststudio syncpermissions`` and
``Admin(sync_permissions_on_startup=True)``. Codenames are
``"<identity>.<action>"`` and the `extra_permissions` of each model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.api._escalation import EscalationRules
from faststudio.api._many import bind_to
from faststudio.auth.capabilities import ACTIONS
from faststudio.query._many import chunks
from faststudio.registry import Registry

#: More codenames than the `permissions` fields of contrib.auth can hold (A3).
MAX_CODENAMES = 10_000


def expected_permissions(registry: Registry) -> dict[str, str]:
    """Return every codename the registered models produce, with a readable name."""
    expected: dict[str, str] = {}
    for registered in registry:
        plural = registered.name_plural.lower()
        for action in ACTIONS:
            expected[f"{registered.identity}.{action}"] = f"Can {action} {plural}"
        for key, description in registered.extra_permissions.items():
            expected[f"{registered.identity}.{key}"] = description or f"Can {key} {plural}"
    return expected


@dataclass(slots=True)
class SyncPlan:
    """What a sync would change."""

    expected: dict[str, str]
    #: Codenames to create.
    missing: list[str] = field(default_factory=list)
    #: Codenames whose name changes.
    renamed: list[str] = field(default_factory=list)
    #: Codenames no registered model produces (renamed identities included).
    stale: list[str] = field(default_factory=list)
    #: Stale codenames that are still granted to users or groups.
    orphaned: list[str] = field(default_factory=list)
    _ids: dict[str, Any] = field(default_factory=dict)


def _assignments(rules: EscalationRules) -> list[tuple[Table, Column[Any]]]:
    """Association tables holding grants, with their column pointing at the permission."""
    found: dict[Any, Column[Any]] = {}
    for side_links in rules.links.values():
        for kind, link in side_links.values():
            if kind in {"user_permissions", "group_permissions"}:
                found[link.secondary] = link.remote_fk
            elif kind in {"permission_users", "permission_groups"}:
                found[link.secondary] = link.local_fk
    return list(found.items())


async def plan_sync(session: AsyncSession, rules: EscalationRules, registry: Registry) -> SyncPlan:
    """Compare the registered codenames with the stored permissions."""
    model = rules.models["permission"]
    pk = _pk(rules)
    expected = expected_permissions(registry)
    columns = [pk, rules.codename, *([rules.name_column] if rules.name_column is not None else [])]
    rows = (await session.execute(select(*columns), bind_arguments=bind_to(model))).all()
    result = SyncPlan(expected=expected)
    stored: dict[str, str | None] = {}
    for row in rows:
        result._ids[row[1]] = row[0]
        stored[row[1]] = row[2] if rules.name_column is not None else None
    result.missing = sorted(set(expected) - set(stored))
    if rules.name_column is not None:
        result.renamed = sorted(c for c in expected if c in stored and stored[c] != expected[c])
    result.stale = sorted(set(stored) - set(expected))
    granted: set[Any] = set()
    stale_ids = [result._ids[c] for c in result.stale]
    for _table, column in _assignments(rules):
        for chunk in chunks(stale_ids):
            statement = select(column).where(column.in_(chunk)).group_by(column)
            granted.update(await session.scalars(statement, bind_arguments=bind_to(model)))
    result.orphaned = [c for c in result.stale if result._ids[c] in granted]
    return result


def _pk(rules: EscalationRules) -> Column[Any]:
    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

    column: Column[Any] = sa_inspect(rules.models["permission"]).primary_key[0]
    return column


async def apply_sync(
    session: AsyncSession, rules: EscalationRules, plan: SyncPlan, *, prune: bool
) -> None:
    """Create missing permissions, update names, and (with `prune`) delete stale ones.

    Runs in the caller's transaction; each insert has its own savepoint, so a
    codename created meanwhile by another worker is tolerated.
    """
    model = rules.models["permission"]
    bind = bind_to(model)
    table = rules.codename.table
    for codename in plan.missing:
        values: dict[Any, Any] = {rules.codename: codename}
        if rules.name_column is not None:
            values[rules.name_column] = plan.expected[codename]
        try:
            async with session.begin_nested():
                await session.execute(insert(table).values(values), bind_arguments=bind)
        except IntegrityError:
            continue  # created concurrently
    if rules.name_column is not None:
        for codename in plan.renamed:
            await session.execute(
                update(table)
                .where(rules.codename == codename)
                .values({rules.name_column: plan.expected[codename]}),
                bind_arguments=bind,
            )
    if prune and plan.stale:
        stale_ids = [plan._ids[c] for c in plan.stale]
        for assignment, column in _assignments(rules):
            for chunk in chunks(stale_ids):
                await session.execute(
                    delete(assignment).where(column.in_(chunk)), bind_arguments=bind
                )
        pk = _pk(rules)
        for chunk in chunks(stale_ids):
            await session.execute(delete(table).where(pk.in_(chunk)), bind_arguments=bind)
