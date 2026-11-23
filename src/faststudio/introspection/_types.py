"""Map SQLAlchemy column types to FastStudio field types (see docs/api-contract.md)."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Interval,
    Numeric,
    PickleType,
    String,
    Text,
    Uuid,
)
from sqlalchemy.types import TypeDecorator, TypeEngine

from faststudio.introspection._columns import base_type

FieldType = Literal[
    "foreign_key",
    "string",
    "text",
    "integer",
    "float",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "enum",
    "json",
    "uuid",
    "unsupported",
]

# Most specific classes first: Enum subclasses String, Text subclasses String,
# Float subclasses Numeric. Numeric is handled separately (asdecimal).
_SIMPLE_TYPES: tuple[tuple[type[TypeEngine[Any]], FieldType], ...] = (
    (Enum, "enum"),
    (Boolean, "boolean"),
    (Text, "text"),
    (Integer, "integer"),
    (Float, "float"),
    (DateTime, "datetime"),
    (Date, "date"),
    (JSON, "json"),
    (Uuid, "uuid"),
    (String, "string"),
)


# SQLAlchemy's own emulated types whose Python values differ from their storage
# type (Interval is stored as DateTime on some backends, PickleType as bytes).
_EMULATED = (Interval, PickleType)


def value_type(column: Column[Any]) -> FieldType:
    """Classify a column by its SQL type alone, ignoring foreign keys."""
    layer: object = column.type
    while True:
        if isinstance(layer, _EMULATED):
            return "unsupported"
        if not isinstance(layer, TypeDecorator):
            break
        layer = layer.impl_instance
    type_ = base_type(column.type)
    if type_ is None:
        return "unsupported"  # dialect-dependent: cannot be validated statically
    for cls, field_type in _SIMPLE_TYPES:
        if isinstance(type_, cls):
            return field_type
    if isinstance(type_, Numeric):
        return "decimal" if type_.asdecimal else "float"
    return "unsupported"


def foreign_key_target(column: Column[Any]) -> Column[Any] | None:
    """Return the referenced primary key for a single-column many-to-one foreign key.

    Only foreign keys to the single-column primary key of the target table are
    relations: choices and labels are served by primary key, never by another
    (possibly excluded) column. Composite foreign keys, columns with several
    foreign keys and foreign keys to non-primary-key columns are plain values.

    Raises:
        sqlalchemy.exc.NoReferenceError: if the target table or column is not
            in the metadata (the registry turns this into ConfigurationError).

    """
    if len(column.foreign_keys) != 1:
        return None
    fk = next(iter(column.foreign_keys))
    if len(fk.constraint.columns) != 1:  # type: ignore[union-attr]  # constraint set once bound
        return None
    target = fk.column
    target_pk = list(target.table.primary_key.columns)
    if len(target_pk) != 1 or target_pk[0] is not target:
        return None
    return target
