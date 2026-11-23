"""Encode database values in the wire format (docs/api-contract.md)."""

from __future__ import annotations

import enum
import math
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.introspection._fields import FieldSpec, JsonValue, is_plain_json
from faststudio.introspection._types import FieldType
from faststudio.query._list import label_statement
from faststudio.registry import RegisteredModel, Registry
from faststudio.schemas.contract import MAX_SAFE_INTEGER, Row

MAX_UNSUPPORTED_LENGTH = 200
MAX_LABEL_LENGTH = 200


def _text(value: object, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_json(value: JsonValue) -> JsonValue:
    """Nested integers outside the JavaScript-safe range become strings too."""
    if isinstance(value, bool) or not isinstance(value, int | list | dict):
        return value
    if isinstance(value, int):
        return value if abs(value) <= MAX_SAFE_INTEGER else str(value)
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return {key: _safe_json(item) for key, item in value.items()}


def encode_value(field_type: FieldType, value: object) -> JsonValue:  # noqa: PLR0911
    """Encode one value for JSON; large integers and decimals become strings."""
    if value is None:
        return None
    if field_type == "integer" and isinstance(value, int):
        return value if abs(value) <= MAX_SAFE_INTEGER else str(value)
    if field_type == "float" and isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if field_type == "decimal" and isinstance(value, Decimal | int | float):
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        return str(number) if number.is_finite() else None
    if field_type in {"date", "datetime"} and isinstance(value, date | datetime):
        return value.isoformat()
    if field_type == "enum":
        return value.name if isinstance(value, enum.Enum) else str(value)
    if field_type == "json":
        return _safe_json(value) if is_plain_json(value) else None
    if field_type in {"string", "text", "uuid"} or (
        field_type == "boolean" and isinstance(value, bool)
    ):
        return value if isinstance(value, bool) else str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(value)} bytes>"
    return _text(value, MAX_UNSUPPORTED_LENGTH)


def encode_field(spec: FieldSpec, value: object) -> JsonValue:
    """Encode a value of `spec`'s field (foreign keys use their own column type)."""
    field_type = spec.relation.value_type if spec.relation is not None else spec.type
    return encode_value(field_type, value)


def encode_pk(value: object) -> str:
    """Primary keys are always strings in URLs and `Row.pk`."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


_ASCII_INT = re.compile(r"-?[0-9]{1,19}")
_INT64 = (-(2**63), 2**63 - 1)


def parse_int_key(raw: str, low: int | None, high: int | None) -> int:
    """Parse an ASCII integer within the column's range (64-bit when unknown)."""
    if not _ASCII_INT.fullmatch(raw):
        raise ValueError(raw)
    value = int(raw)
    lower = _INT64[0] if low is None else low
    upper = _INT64[1] if high is None else high
    if not lower <= value <= upper:
        raise ValueError(raw)
    return value


def _parse_decimal(raw: str) -> Decimal:
    number = Decimal(raw)
    if not number.is_finite():
        raise ValueError(raw)
    return number


_PK_PARSERS: dict[str, Callable[[str], object]] = {
    "uuid": UUID,
    "decimal": _parse_decimal,
    "date": date.fromisoformat,
    "datetime": datetime.fromisoformat,
    "string": str,
    "text": str,
}


def parse_key(
    field_type: str, raw: str, *, low: int | None = None, high: int | None = None
) -> object | None:
    """Parse a key of `field_type` from text; None if it cannot be a valid key."""
    try:
        if field_type == "integer":
            return parse_int_key(raw, low, high)
        parser = _PK_PARSERS.get(field_type)
        return parser(raw) if parser is not None else None
    except (ValueError, InvalidOperation):
        return None


def parse_pk(registered: RegisteredModel, raw: str) -> object | None:
    """Parse a primary key from a URL; None if it cannot be a valid key."""
    spec = registered.field_specs[registered.pk_field]
    field_type = spec.relation.value_type if spec.relation is not None else spec.type
    return parse_key(field_type, raw, low=spec.min_value, high=spec.max_value)


def format_label(pk: object, label: object) -> str:
    """Display label of a related record: its label value, or its key when empty."""
    if label is None or label == "":
        return encode_pk(pk)
    if isinstance(label, datetime | date):
        return label.isoformat()
    return _text(label, MAX_LABEL_LENGTH)


async def relation_labels(
    session: AsyncSession,
    registry: Registry,
    registered: RegisteredModel,
    rows: Sequence[object],
    fields: Sequence[str],
) -> list[dict[str, str]]:
    """Display labels of foreign-key values, one query per relation field."""
    labels: list[dict[str, str]] = [{} for _ in rows]
    for name in fields:
        spec = registered.field_specs[name]
        target = registry.target_of(spec.relation.target) if spec.relation else None
        if target is None:
            continue
        values = {getattr(row, name) for row in rows} - {None}
        if not values:
            continue
        result = await session.execute(label_statement(target, values))
        by_pk = {pk: format_label(pk, label) for pk, label in result.all()}
        for index, row in enumerate(rows):
            value = getattr(row, name)
            if value in by_pk:
                labels[index][name] = by_pk[value]
    return labels


def to_row(
    registered: RegisteredModel,
    obj: object,
    fields: Sequence[str],
    labels: dict[str, str],
) -> Row:
    """Serialize one ORM object: primary key, the given visible fields, labels."""
    specs = registered.field_specs
    return Row(
        pk=encode_pk(getattr(obj, registered.pk_field)),
        data={name: encode_field(specs[name], getattr(obj, name)) for name in fields},
        labels=labels,
    )
