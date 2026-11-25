"""Reading many-to-many fields for detail rows (ADR-0010 §3-4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.api._serialize import encode_pk, encode_value, format_label
from faststudio.introspection._fields import JsonValue
from faststudio.introspection._many import ManyToManyField
from faststudio.query._list import label_statement
from faststudio.query._many import chunks, linked_keys_statement
from faststudio.registry import RegisteredModel, Registry


@dataclass(slots=True)
class ManyValues:
    """Encoded keys, their labels and the truncated fields of one record."""

    keys: dict[str, list[JsonValue]] = field(default_factory=dict)
    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    truncated: list[str] = field(default_factory=list)


def bind_to(model: type[Any]) -> dict[str, Any]:
    """`bind_arguments` for Core statements on a model's association tables.

    They name no mapped entity, so a session factory that routes engines only
    through `binds={Base: engine}` could not resolve them; the record's mapper can.
    """
    return {"mapper": sa_inspect(model)}


async def linked_keys(
    session: AsyncSession, model: type[Any], many: ManyToManyField, pk: object, limit: int
) -> list[object]:
    """Distinct keys linked to `pk`, at most `limit` (explicit query, no lazy loading)."""
    statement = linked_keys_statement(many.link, pk, limit)
    return list((await session.scalars(statement, bind_arguments=bind_to(model))).all())


async def many_values(
    session: AsyncSession, registry: Registry, registered: RegisteredModel, pk: object
) -> ManyValues:
    """Load every many-to-many field of the record `pk`.

    Each field reads at most `max_items + 1` keys: one more than allowed marks
    the field as truncated (and only `max_items` keys are returned). Labels
    come from the target model when it is registered, else they are the keys.
    """
    result = ManyValues()
    for name, many in registered.many_to_many.items():
        keys = await linked_keys(session, registered.model, many, pk, many.max_items + 1)
        if len(keys) > many.max_items:
            result.truncated.append(name)
            keys = keys[: many.max_items]
        result.keys[name] = [encode_value(many.link.value_type, key) for key in keys]
        labels = {encode_pk(key): encode_pk(key) for key in keys}
        target = registry.target_of(many.link.target_pk)
        if target is not None:
            for chunk in chunks(keys):
                rows = await session.execute(label_statement(target, chunk))
                for key, label in rows.all():
                    labels[encode_pk(key)] = format_label(key, label)
        result.labels[name] = labels
    return result
