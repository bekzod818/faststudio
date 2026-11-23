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
        columns = [_canonical(c) for c in prop.columns if isinstance(c, Column)]
        local = [c for c in columns if c.table is mapper.local_table]
        own = [c for c in columns if id(c.table) in own_tables]
        chosen = next(iter(local or own), None)
        if chosen is not None:
            result[prop.key] = chosen
    return result


def _canonical(column: Column[Any]) -> Column[Any]:
    """Return the table's own ``Column`` object.

    ``column_property(Model.attr)`` stores an *annotated copy* of the column, a
    different object from ``Model.__table__.c.attr``. Identity comparisons (for
    example "is this attribute an alias of an excluded column?") are only sound
    on the canonical object.
    """
    table_columns = getattr(column.table, "c", None)
    canonical = table_columns.get(column.key) if table_columns is not None else None
    return canonical if isinstance(canonical, Column) else column


def base_type(type_: TypeEngine[Any]) -> TypeEngine[Any] | None:
    """Unwrap ``TypeDecorator`` layers; ``None`` if the type is dialect-dependent.

    Types whose implementation depends on the database dialect (``with_variant``
    or a ``TypeDecorator`` overriding ``load_dialect_impl``) cannot be classified
    safely without an engine and are treated as unknown.
    """
    while True:
        # `_variant_mapping` is private SQLAlchemy API (checked against 2.0 and 2.1);
        # tests with `with_variant()` columns catch any change in behaviour.
        if getattr(type_, "_variant_mapping", None):
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
