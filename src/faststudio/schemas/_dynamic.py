"""Per-model write schemas generated at `register()` (threat model T5).

`Create` contains the fields a client may set on creation, `Update` the
fields it may change afterwards. Both forbid unknown keys, so readonly,
excluded, primary-key and misspelled fields are rejected with 422 instead
of being silently ignored or written. Values are validated at least as
strictly as the database will check them.

Field names never clash with pydantic internals: every field gets a
generated attribute name (`f0`, `f1`, ...) and the model attribute name as
its JSON alias, so columns such as `model_config`, `json` or `_hidden`
work like any other.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    AllowInfNan,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    Strict,
    create_model,
)
from sqlalchemy import Enum

from faststudio.introspection._columns import base_type
from faststudio.introspection._fields import FieldSpec
from faststudio.introspection._types import FieldType
from faststudio.schemas.contract import MAX_SAFE_INTEGER

#: A pydantic annotation object (a "type form"; PEP 747 will give it a precise type).
_Annotation: TypeAlias = Any

#: Length cap for every string/text value, also when the column is longer.
MAX_TEXT_LENGTH = 65_535
_ASCII_INT = re.compile(r"-?[0-9]{1,19}")
_CANONICAL_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class WriteSchema(BaseModel):
    """Base of generated write models: closed, value-free errors, aliased fields."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    #: internal field name -> model attribute name (the JSON key).
    field_map: ClassVar[Mapping[str, str]] = {}

    def submitted(self) -> dict[str, Any]:
        """Values of the fields the client actually sent, keyed by attribute name."""
        return {self.field_map[name]: getattr(self, name) for name in self.model_fields_set}


def _no_nul(value: str) -> str:
    if "\x00" in value:
        msg = "must not contain NUL characters"
        raise ValueError(msg)
    return value


def _int_from_digits(value: object) -> object:
    # Large integers travel as strings on the wire (JavaScript precision).
    if isinstance(value, str) and _ASCII_INT.fullmatch(value):
        return int(value)
    return value


def _canonical_uuid(value: object) -> object:
    if isinstance(value, str) and not _CANONICAL_UUID.fullmatch(value):
        msg = "must be a UUID in the form 8-4-4-4-12 hexadecimal digits"
        raise ValueError(msg)
    return value


def _json_value(value: JsonValue) -> JsonValue:
    """Reject what JSON columns cannot store faithfully (NaN, NUL) or the SPA cannot read back."""
    if isinstance(value, float) and not math.isfinite(value):
        msg = "JSON numbers must be finite"
        raise ValueError(msg)
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_SAFE_INTEGER:
        msg = "JSON integers must be within ±(2**53 - 1); send larger numbers as strings"
        raise ValueError(msg)
    if isinstance(value, str):
        _no_nul(value)
    elif isinstance(value, list):
        for item in value:
            _json_value(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _no_nul(key)
            _json_value(item)
    return value


def _naive_only(value: datetime) -> datetime:
    if value.tzinfo is not None:
        msg = "this field stores local time without a timezone"
        raise ValueError(msg)
    return value


def _assume_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _string(spec: FieldSpec) -> _Annotation:
    limit = min(spec.max_length or MAX_TEXT_LENGTH, MAX_TEXT_LENGTH)
    return Annotated[str, Strict(), Field(max_length=limit), AfterValidator(_no_nul)]


def _integer(spec: FieldSpec) -> _Annotation:
    return Annotated[
        int,
        BeforeValidator(_int_from_digits),
        Strict(),
        Field(ge=spec.min_value, le=spec.max_value),
    ]


def _decimal(spec: FieldSpec) -> _Annotation:
    return Annotated[
        Decimal,
        AllowInfNan(False),
        Field(max_digits=spec.precision, decimal_places=spec.scale),
    ]


def _enum(spec: FieldSpec) -> _Annotation:
    names = tuple(choice.value for choice in spec.choices or ())
    type_ = base_type(spec.column.type)
    enum_class = type_.enum_class if isinstance(type_, Enum) else None
    convert: Callable[[str], object] = (
        (lambda name: enum_class[name]) if enum_class is not None else (lambda name: name)
    )
    return Annotated[Literal[names], AfterValidator(convert)]


def _datetime(spec: FieldSpec) -> _Annotation:
    return Annotated[
        datetime, Strict(), AfterValidator(_assume_utc if spec.timezone else _naive_only)
    ]


_SIMPLE: Mapping[FieldType, _Annotation] = {
    # Strict float still accepts JSON integers, but not booleans or strings.
    "float": Annotated[float, Strict(), AllowInfNan(False)],
    "boolean": Annotated[bool, Strict()],
    # Strict dates/UUIDs accept only their JSON string forms (no numbers).
    "date": Annotated[date, Strict()],
    "uuid": Annotated[uuid.UUID, BeforeValidator(_canonical_uuid)],
    "json": Annotated[JsonValue, AfterValidator(_json_value)],
}
_BUILDERS: Mapping[FieldType, Callable[[FieldSpec], _Annotation]] = {
    "string": _string,
    "text": _string,
    "integer": _integer,
    "decimal": _decimal,
    "enum": _enum,
    "datetime": _datetime,
}
#: Field types that can be written (everything except `foreign_key`, which uses
#: its own column type, and `unsupported`, which is always readonly).
WRITABLE_TYPES: frozenset[FieldType] = frozenset({*_SIMPLE, *_BUILDERS})


def value_annotation(spec: FieldSpec) -> _Annotation:
    """Pydantic type for one writable field (foreign keys use their own column type)."""
    field_type = spec.relation.value_type if spec.relation is not None else spec.type
    builder = _BUILDERS.get(field_type)
    annotation = builder(spec) if builder is not None else _SIMPLE[field_type]
    return annotation | None if spec.nullable else annotation


@dataclass(frozen=True, slots=True)
class ManyKeys:
    """A writable many-to-many field: a list of target keys (ADR-0010)."""

    name: str
    #: Describes the target's primary key: each key is validated like it.
    key_spec: FieldSpec
    max_items: int


def _distinct_keys(keys: list[object]) -> list[object]:
    if len(set(keys)) != len(keys):
        msg = "must not contain duplicate keys"
        raise ValueError(msg)
    return keys


def many_annotation(field: ManyKeys) -> _Annotation:
    """`[key, ...]`: each key typed like the target primary key, bounded, distinct, not null."""
    key = value_annotation(replace(field.key_spec, nullable=False))
    return Annotated[list[key], Field(max_length=field.max_items), AfterValidator(_distinct_keys)]  # type: ignore[valid-type]  # built at runtime


def _model(
    name: str, specs: list[FieldSpec], many: Sequence[ManyKeys], *, all_optional: bool
) -> type[WriteSchema]:
    fields: dict[str, Any] = {}
    field_map: dict[str, str] = {}
    for index, spec in enumerate(specs):
        internal = f"f{index}"
        field_map[internal] = spec.name
        default: Any = ... if spec.required and not all_optional else None
        fields[internal] = (value_annotation(spec), Field(default, alias=spec.name))
    for index, field in enumerate(many):
        internal = f"m{index}"
        field_map[internal] = field.name
        fields[internal] = (many_annotation(field), Field(None, alias=field.name))
    model = cast("type[WriteSchema]", create_model(name, __base__=WriteSchema, **fields))
    model.field_map = field_map
    return model


def build_write_schemas(
    model_name: str, field_specs: Mapping[str, FieldSpec], many: Sequence[ManyKeys] = ()
) -> tuple[type[WriteSchema], type[WriteSchema]]:
    """Return `(Create, Update)` models; only explicitly sent fields are written.

    `many` lists the writable (opted-in, not readonly) many-to-many fields.
    """
    creatable = [s for s in field_specs.values() if not s.readonly]
    updatable = [s for s in creatable if not s.create_only]
    return (
        _model(f"{model_name}Create", creatable, many, all_optional=False),
        _model(f"{model_name}Update", updatable, many, all_optional=True),
    )
