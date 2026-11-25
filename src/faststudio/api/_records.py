"""Loading records and building `Row` responses (shared by read and write routes)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.api._many import many_values
from faststudio.api._serialize import parse_pk, relation_labels, to_row
from faststudio.api.errors import ApiError
from faststudio.registry import RegisteredModel, Registry
from faststudio.schemas.contract import Row


async def load_or_404(session: AsyncSession, registered: RegisteredModel, pk: str) -> object:
    """Load one record of `registered` by its URL key, or raise 404."""
    key = parse_pk(registered, pk)
    obj = await session.get(registered.model, key) if key is not None else None
    if obj is None:
        raise ApiError(404, "not_found")
    return obj


async def detail_row(
    session: AsyncSession, registry: Registry, registered: RegisteredModel, obj: object
) -> Row:
    """`Row` with every visible field and relation labels."""
    fields = list(registered.fields)
    (labels,) = await relation_labels(session, registry, registered, [obj], fields)
    many = await many_values(session, registry, registered, getattr(obj, registered.pk_field))
    return to_row(
        registered,
        obj,
        fields,
        labels,
        many=many.keys,
        many_labels=many.labels,
        truncated=many.truncated,
    )
