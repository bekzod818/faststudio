"""Low-level helpers to read mapped columns from a SQLAlchemy mapper."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Column, Enum, String
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeDecorator, TypeEngine


def mapped_columns(mapper: Mapper[Any]) -> dict[str, Column[Any]]:
    """Return ``{attribute key: Column}`` for the mapper's own column attributes.

    For each column attribute, the column on the mapper's local table is used
    (joined-table inheritance maps the primary key to several columns), falling
    back to any column of the mapper's tables. Attributes backed only by
    SQL expressions or by columns of unrelated tables are not fields.
    Declaration order is preserved.
    """
    own_tables = {id(table) for table in mapper.tables}
    result: dict[str, Column[Any]] = {}
    for prop in mapper.column_attrs:
        columns = [canonical_column(c) for c in prop.columns if isinstance(c, Column)]
        local = [c for c in columns if c.table is mapper.local_table]
        own = [c for c in columns if id(c.table) in own_tables]
        chosen = next(iter(local or own), None)
        if chosen is not None:
            result[prop.key] = chosen
    return result


def canonical_column(column: Column[Any]) -> Column[Any]:
    """Return the table's own ``Column`` object.

    ``column_property(Model.attr)`` stores an *annotated copy* of the column, a
    different object from ``Model.__table__.c.attr``. Identity comparisons (for
    example "is this attribute an alias of an excluded column?") are only sound
    on the canonical object.
    """
    table_columns = getattr(column.table, "c", None)
    canonical = table_columns.get(column.key) if table_columns is not None else None
    return canonical if isinstance(canonical, Column) else column


# Hooks through which a type can transform values on the way to or from the
# database. Overriding any of them means the Python type may differ from the
# storage type, so the column cannot be classified by its base type.
_VALUE_HOOKS = (
    "process_bind_param",
    "process_result_value",
    "bind_processor",
    "result_processor",
    "bind_expression",
    "column_expression",
)


def _builtin_base(cls: type[Any]) -> type[Any]:
    """Return the nearest SQLAlchemy-defined class in ``cls``'s MRO."""
    return next(k for k in cls.__mro__ if k.__module__.startswith("sqlalchemy."))


def _converts_values(type_: TypeEngine[Any]) -> bool:
    cls = type(type_)
    base = TypeDecorator if isinstance(type_, TypeDecorator) else _builtin_base(cls)
    return any(getattr(cls, hook, None) is not getattr(base, hook, None) for hook in _VALUE_HOOKS)


def base_type(type_: TypeEngine[Any]) -> TypeEngine[Any] | None:
    """Unwrap ``TypeDecorator`` layers; ``None`` if the type cannot be classified.

    Returns ``None`` (fail closed) for types whose implementation depends on the
    database dialect (``with_variant``, a ``TypeDecorator`` overriding
    ``load_dialect_impl``) and for types that convert values through any of
    ``_VALUE_HOOKS`` (custom ``TypeDecorator``s or direct subclasses of built-in
    types): their Python type may differ from the storage type, e.g. JSON
    stored as VARCHAR or values encrypted in SQL.
    """
    while True:
        # `_variant_mapping` is private SQLAlchemy API (checked against 2.0 and 2.1);
        # tests with `with_variant()` columns catch any change in behaviour.
        if getattr(type_, "_variant_mapping", None):
            return None
        if _converts_values(type_):
            return None
        if not isinstance(type_, TypeDecorator):
            return type_
        if type(type_).load_dialect_impl is not TypeDecorator.load_dialect_impl:
            return None
        type_ = type_.impl_instance


def is_text(column: Column[Any]) -> bool:
    """Return True for string/text columns (not ``Enum``, which subclasses ``String``)."""
    type_ = base_type(column.type)
    return isinstance(type_, String) and not isinstance(type_, Enum)


def is_filterable(column: Column[Any]) -> bool:
    """Return True for column types ``list_filter`` supports in v0.1: boolean and enum."""
    return isinstance(base_type(column.type), Boolean | Enum)
