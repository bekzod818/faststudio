"""Build :class:`FieldSpec` descriptions of mapped columns."""

from __future__ import annotations

import enum
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TypeAlias, cast

from sqlalchemy import (
    BigInteger,
    Column,
    ColumnDefault,
    Computed,
    DateTime,
    DefaultClause,
    Enum,
    FetchedValue,
    Identity,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy import Sequence as DbSequence

from faststudio.introspection._columns import base_type
from faststudio.introspection._types import FieldType, foreign_key_target, value_type

JsonValue: TypeAlias = "str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None"

_ACRONYMS = {"id": "ID", "uuid": "UUID", "url": "URL", "ip": "IP", "api": "API", "json": "JSON"}
# Whole '_'-separated name segments only, so "passenger_count" or "hashtag" do not match.
_SENSITIVE = re.compile(
    r"(?:^|_)(?:pass(?:word|wd)?|pwd|hash(?:ed)?|secret|token|api_?key|salt|otp)(?:_|$)",
    re.IGNORECASE,
)
# Portable integer ranges (the narrowest common SQL definition of each type).
_INT_RANGES: tuple[tuple[type[Any], int, int], ...] = (
    (SmallInteger, -(2**15), 2**15 - 1),
    (BigInteger, -(2**63), 2**63 - 1),
)
_INT_DEFAULT_RANGE = (-(2**31), 2**31 - 1)


@dataclass(frozen=True, slots=True)
class Choice:
    """One allowed value of an enum field: wire ``value`` and display ``label``."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class Relation:
    """Many-to-one foreign key to a primary key. ``value_type`` is the FK column's own type."""

    target: Column[Any] = field(compare=False)
    value_type: FieldType


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Everything FastStudio knows about one visible field of a model.

    ``readonly`` fields are never accepted on create or update. ``create_only``
    fields (natural primary keys) are accepted on create and never on update.
    """

    name: str
    label: str
    type: FieldType
    nullable: bool
    required: bool
    readonly: bool
    create_only: bool
    primary_key: bool
    default: JsonValue
    has_default: bool
    max_length: int | None
    min_value: int | None
    max_value: int | None
    choices: tuple[Choice, ...] | None
    relation: Relation | None
    timezone: bool | None
    precision: int | None
    scale: int | None
    help_text: str | None
    column: Column[Any] = field(repr=False, compare=False)


def build_field_spec(
    key: str,
    column: Column[Any],
    *,
    label: str | None,
    readonly: bool,
    siblings: Sequence[Column[Any]] = (),
    managed: bool = False,
) -> FieldSpec:
    """Describe ``column`` mapped at attribute ``key``.

    Args:
        key: Mapped attribute name.
        column: The table's own column object.
        label: Explicit display label (``column_labels``), else humanized.
        readonly: Listed in ``readonly_fields``.
        siblings: Other columns of the same attribute (joined-table inheritance
            maps the primary key to the subclass and parent columns; the join
            foreign key is not a relation).
        managed: The mapper maintains the value (polymorphic discriminator,
            ``version_id_col``).

    """
    for fk in column.foreign_keys:
        # Resolve first: an FK column without an explicit type takes its type from
        # the target, and a missing target table must fail loudly (NoReferenceError).
        _ = fk.column
    all_columns = [column, *siblings]
    generated = managed or is_generated(all_columns)
    own_type = value_type(column)
    target = foreign_key_target(column) if own_type != "unsupported" else None
    if target is not None and any(target is c for c in all_columns):
        target = None  # inheritance join to the parent table, not a relation
    field_type: FieldType = "foreign_key" if target is not None else own_type
    unsupported = own_type == "unsupported"
    has_default = column.default is not None or column.server_default is not None
    natural_pk = column.primary_key and not generated and not has_default
    create_only = natural_pk and not readonly and not unsupported
    readonly = readonly or generated or unsupported or (column.primary_key and not create_only)
    required = is_required_column(column, siblings, managed=managed) and not readonly
    type_ = base_type(column.type)
    publish_default = not unsupported and not looks_sensitive(key)
    min_value, max_value = _int_range(type_) if own_type == "integer" else (None, None)
    return FieldSpec(
        name=key,
        label=label or humanize(key, strip_id=target is not None),
        type=field_type,
        nullable=bool(column.nullable),
        required=required,
        readonly=readonly,
        create_only=create_only,
        primary_key=column.primary_key,
        default=_scalar_default(column.default, own_type) if publish_default else None,
        has_default=has_default,
        max_length=type_.length if own_type == "string" and isinstance(type_, String) else None,
        min_value=min_value,
        max_value=max_value,
        choices=_choices(type_) if field_type == "enum" else None,
        relation=Relation(target, own_type) if target is not None else None,
        timezone=bool(type_.timezone)
        if own_type == "datetime" and isinstance(type_, DateTime)
        else None,
        precision=type_.precision if own_type == "decimal" and isinstance(type_, Numeric) else None,
        scale=type_.scale if own_type == "decimal" and isinstance(type_, Numeric) else None,
        help_text=column.comment or None,
        column=column,
    )


def is_generated(columns: Sequence[Column[Any]]) -> bool:
    """Return True if the database or SQLAlchemy maintains the value.

    Covers autoincrement keys, ``Identity``, ``Computed``, ``Sequence``
    defaults, trigger-filled server defaults (``FetchedValue``) and columns
    with ``onupdate``/``server_onupdate`` (e.g. ``updated_at``).
    """
    for column in columns:
        table = getattr(column, "table", None)
        if table is not None and table.autoincrement_column is column:
            return True
        if isinstance(column.identity, Identity) or isinstance(column.computed, Computed):
            return True
        if isinstance(column.default, DbSequence):
            return True
        server_default = column.server_default
        if isinstance(server_default, FetchedValue) and not isinstance(
            server_default, DefaultClause
        ):
            return True
        if column.onupdate is not None or column.server_onupdate is not None:
            return True
    return False


def is_required_column(
    column: Column[Any], siblings: Sequence[Column[Any]] = (), *, managed: bool = False
) -> bool:
    """Return True if inserts fail unless the client supplies a value for ``column``."""
    has_default = column.default is not None or column.server_default is not None
    generated = managed or is_generated([column, *siblings])
    return not column.nullable and not has_default and not generated


def looks_sensitive(name: str) -> bool:
    """Match sensitive words as whole segments of snake_case or camelCase names."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return bool(_SENSITIVE.search(snake))


def humanize(name: str, *, strip_id: bool = False) -> str:
    """``created_at`` -> ``Created at``; ``team_id`` (a relation) -> ``Team``."""
    if strip_id and name.endswith("_id") and len(name) > len("_id"):
        name = name[: -len("_id")]
    words = [w for w in name.split("_") if w]
    if not words:
        return name
    out = [_ACRONYMS.get(w.lower(), w.lower()) for w in words]
    first = out[0]
    out[0] = first if first.isupper() else first[:1].upper() + first[1:]
    return " ".join(out)


def json_default(value: object, field_type: FieldType | None = None) -> JsonValue:
    """Convert a Python default to its wire form, or ``None`` if it has none.

    ``decimal`` fields are always strings on the wire, so numeric defaults on
    them are converted (``1.5`` -> ``"1.5"``).
    """
    is_number = isinstance(value, int | float | Decimal) and not isinstance(value, bool)
    if is_number and field_type == "float":
        number = float(value)  # type: ignore[arg-type]  # narrowed by is_number
        return number if math.isfinite(number) else None
    if is_number and (field_type == "decimal" or isinstance(value, Decimal)):
        decimal = Decimal(str(value))
        return str(decimal) if decimal.is_finite() else None
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, datetime | date | time | uuid.UUID):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    return cast("JsonValue", value) if _is_plain_json(value) else None


def _is_plain_json(value: object) -> bool:
    if value is None or isinstance(value, str | bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_plain_json(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_plain_json(v) for k, v in value.items())
    return False


def _scalar_default(default: object, field_type: FieldType) -> JsonValue:
    if isinstance(default, ColumnDefault) and default.is_scalar:
        return json_default(default.arg, field_type)
    return None


def _int_range(type_: object) -> tuple[int, int]:
    for cls, low, high in _INT_RANGES:
        if isinstance(type_, cls):
            return low, high
    return _INT_DEFAULT_RANGE


def _choices(type_: object) -> tuple[Choice, ...]:
    if not isinstance(type_, Enum):  # pragma: no cover - guarded by the caller
        return ()
    if type_.enum_class is not None:
        names = [member.name for member in type_.enum_class]
    else:
        names = list(type_.enums)
    return tuple(Choice(name, humanize(name)) for name in names)
