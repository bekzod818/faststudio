"""Build list, count, label and choices statements from validated parameters.

Statements select through the mapped entity (`select(Model)` or its
instrumented attributes), never bare table columns, so SQLAlchemy adds the
joins and discriminator criteria of joined and single-table inheritance.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, true
from sqlalchemy.orm import InstrumentedAttribute, load_only

from faststudio.query._params import CHOICES_PAGE_SIZE, ListParams
from faststudio.registry import RegisteredModel, label_field


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so user text matches literally (escape character: backslash)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def attribute(registered: RegisteredModel, name: str) -> InstrumentedAttribute[Any]:
    """Return the entity attribute of an allowlisted field (never called with raw input)."""
    attr: InstrumentedAttribute[Any] = getattr(registered.model, name)
    return attr


def search_condition(
    columns: Iterable[InstrumentedAttribute[Any]], q: str | None
) -> ColumnElement[bool] | None:
    """Case-insensitive contains-match of `q` on any of `columns` (bound parameters only)."""
    targets = list(columns)
    if not q or not targets:
        return None
    pattern = f"%{escape_like(q)}%"
    return or_(*(column.ilike(pattern, escape="\\") for column in targets))


def _conditions(registered: RegisteredModel, params: ListParams) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    columns = (attribute(registered, name) for name in registered.search_fields)
    search = search_condition(columns, params.q)
    if search is not None:
        conditions.append(search)
    for name, value in params.filters.items():
        column = attribute(registered, name)
        conditions.append(column.is_(None) if value is None else column == value)
    return conditions


def list_statements(
    registered: RegisteredModel, params: ListParams
) -> tuple[Select[Any], Select[Any]]:
    """Return `(page query, count query)` for one list request.

    Only the primary key and `list_display` columns are loaded, so excluded
    or large columns are never fetched for lists.
    """
    pk = attribute(registered, registered.pk_field)
    where = and_(true(), *_conditions(registered, params))
    order = [
        attribute(registered, name).desc() if descending else attribute(registered, name).asc()
        for name, descending in params.ordering
    ]
    if registered.pk_field not in {name for name, _ in params.ordering}:
        order.append(pk.asc())  # stable pagination
    loaded = {registered.pk_field, *registered.list_display}
    page = (
        select(registered.model)
        .options(load_only(*(attribute(registered, name) for name in loaded)))
        .where(where)
        .order_by(*order)
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
    )
    count = select(func.count()).select_from(select(pk).where(where).subquery())
    return page, count


def label_statement(target: RegisteredModel, values: Iterable[object]) -> Select[Any]:
    """`(pk, label)` rows of `target` for the given primary keys."""
    pk = attribute(target, target.pk_field)
    label = attribute(target, label_field(target))
    return select(pk, label).where(pk.in_(list(values)))


def choices_statements(
    target: RegisteredModel, q: str | None, page: int
) -> tuple[Select[Any], Select[Any]]:
    """Return `(page query, count query)` of `(pk, label)` options for a relation."""
    pk = attribute(target, target.pk_field)
    label_name = label_field(target)
    label = attribute(target, label_name)
    names = list(target.search_fields)
    if not names and target.field_specs[label_name].type in {"string", "text"}:
        names = [label_name]
    condition = search_condition((attribute(target, n) for n in names), q)
    base = select(pk, label).where(condition if condition is not None else true())
    count = select(func.count()).select_from(base.subquery())
    page_query = (
        base.order_by(label.asc(), pk.asc())
        .offset((page - 1) * CHOICES_PAGE_SIZE)
        .limit(CHOICES_PAGE_SIZE)
    )
    return page_query, count
