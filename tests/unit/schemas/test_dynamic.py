"""Generated write schemas (mass-assignment protection, threat model T5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, get_args

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ConfigurationError, ModelAdmin
from faststudio.introspection._types import FieldType
from faststudio.registry import RegisteredModel
from faststudio.schemas._dynamic import WRITABLE_TYPES, WriteSchema
from tests._stubs import StubAuthBackend
from tests.factories.models import (
    AllTypes,
    Awkward,
    Country,
    Doc,
    Engineer,
    Note,
    Role,
    Ticket,
    Twin,
    Versioned,
)


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _reg(admin: Admin, model: type[Any], **options: Any) -> RegisteredModel:
    admin.register(type(f"{model.__name__}A", (ModelAdmin,), dict(options), model=model))
    return next(r for r in admin._registry if r.model is model)


def _keys(schema: type[WriteSchema]) -> set[str]:
    return set(schema.field_map.values())


def _parse(schema: type[WriteSchema], body: dict[str, Any]) -> dict[str, Any]:
    return schema.model_validate_json(json.dumps(body)).submitted()


def test_schema_fields_follow_writability(admin: Admin) -> None:
    note = _reg(admin, Note, exclude=["secret"], readonly_fields=["created_at"])
    create = _keys(note.create_schema)
    assert create == {"title", "body", "priority", "status", "due", "stamped", "team_id"}
    assert _keys(note.update_schema) == create
    with pytest.raises(ValidationError):
        _parse(note.create_schema, {"body": "no title"})
    assert _parse(note.update_schema, {}) == {}


def test_natural_key_is_create_only(admin: Admin) -> None:
    country = _reg(admin, Country)
    assert "code" in _keys(country.create_schema)
    assert "code" not in _keys(country.update_schema)


@pytest.mark.parametrize(
    ("model", "absent"),
    [
        (Ticket, {"id", "number"}),  # server-chosen UUID pk, Identity column
        (Versioned, {"id", "version"}),  # version_id_col is managed
        (Engineer, {"id", "kind"}),  # inheritance pk and discriminator
    ],
)
def test_generated_and_managed_columns_are_never_writable(
    admin: Admin, model: type[Any], absent: set[str]
) -> None:
    registered = _reg(admin, model)
    for schema in (registered.create_schema, registered.update_schema):
        assert not absent & _keys(schema)


def test_names_that_clash_with_pydantic_are_aliased(admin: Admin) -> None:
    awkward = _reg(admin, Awkward)
    body = {"model_config": "a", "json": "b", "_hidden": "c"}
    assert _parse(awkward.create_schema, body) == body
    with pytest.raises(ValidationError):
        _parse(awkward.create_schema, {"f0": "internal names are not accepted"})


def test_readonly_column_aliases_fail_registration(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="'created_alias' maps to the same column"):
        _reg(admin, Doc, readonly_fields=["created_at"])


def test_readonly_aliases_together_are_accepted(admin: Admin) -> None:
    doc = _reg(admin, Doc, readonly_fields=["created_at", "created_alias"])
    assert _keys(doc.update_schema) == set()


def test_every_writable_field_type_has_a_validator() -> None:
    # Foreign keys use the target's type; many-to-many fields have their own list schema.
    assert set(get_args(FieldType)) - WRITABLE_TYPES == {
        "foreign_key",
        "many_to_many",
        "unsupported",
    }


@pytest.fixture
def all_types(admin: Admin) -> RegisteredModel:
    return _reg(admin, AllTypes, can_create=False)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("u_uuid", "00000000-0000-0000-0000-000000000003", uuid.UUID(int=3)),
        ("j_json", {"a": [1, "b", None, 1.5]}, {"a": [1, "b", None, 1.5]}),
        ("f_float", 2, 2.0),
        ("f_float", 2.5, 2.5),
        ("b_bool", True, True),
        ("dt_date", "2026-01-02", date(2026, 1, 2)),
        ("d_numeric", "12.30", Decimal("12.30")),
        ("e_strings", "draft", "draft"),
        ("e_enum", "VIEWER", Role.VIEWER),
        ("dt_aware", "2026-01-02T03:04:05+00:00", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("dt_aware", "2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("dt_naive", "2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5)),
        ("i_big", str(2**62), 2**62),
        ("i_int", "007", 7),
    ],
)
def test_valid_values(
    all_types: RegisteredModel, field: str, value: object, expected: object
) -> None:
    assert _parse(all_types.update_schema, {field: value}) == {field: expected}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("u_uuid", "nope"),
        ("u_uuid", "{00000000-0000-0000-0000-000000000003}"),
        ("u_uuid", "urn:uuid:00000000-0000-0000-0000-000000000003"),
        ("u_uuid", "00000000000000000000000000000003"),
        ("f_float", "1.5"),
        ("f_float", True),
        ("b_bool", "true"),
        ("b_bool", 1),
        ("dt_date", "02/01/2026"),
        ("dt_date", 0),
        ("dt_date", "2026-01-02T00:00:00"),
        ("dt_naive", 1_700_000_000),
        ("dt_naive", "2026-01-02T03:04:05Z"),
        ("d_numeric", "1.234"),
        ("e_strings", "Draft"),
        ("i_small", 2**15),
        ("i_big", str(2**63)),
        ("s_len", "x" * 51),
        ("s_nolen", "x" * 65_536),
        ("j_json", {"k": "nul\u0000"}),
        ("j_json", {"nul\u0000": 1}),
        ("j_json", [2**60]),
        ("x_time", "12:00"),  # unsupported: not writable at all
    ],
)
def test_invalid_values(all_types: RegisteredModel, field: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _parse(all_types.update_schema, {field: value})
    assert "input_value" not in str(exc_info.value)  # submitted values are hidden


@pytest.mark.parametrize("raw", ['{"j_json": NaN}', '{"j_json": [Infinity]}', '{"f_float": NaN}'])
def test_non_finite_json_numbers_are_rejected(all_types: RegisteredModel, raw: str) -> None:
    with pytest.raises(ValidationError):
        all_types.update_schema.model_validate_json(raw)


def test_two_writable_attributes_on_one_column_fail_registration(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="map to the same column"):
        _reg(admin, Twin)


def test_excluding_both_attributes_is_accepted(admin: Admin) -> None:
    twin = _reg(admin, Twin, exclude=["label", "label_alias"])
    assert _keys(twin.update_schema) == set()


def test_marking_both_attributes_readonly_is_accepted(admin: Admin) -> None:
    twin = _reg(admin, Twin, readonly_fields=["label", "label_alias"])
    assert _keys(twin.update_schema) == set()
