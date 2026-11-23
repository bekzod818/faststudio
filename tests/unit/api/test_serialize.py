"""Wire encoding of database values and URL primary keys."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ModelAdmin
from faststudio.api._serialize import encode_pk, encode_value, format_label, parse_key, parse_pk
from faststudio.registry import RegisteredModel, label_field
from tests._stubs import StubAuthBackend
from tests.factories.models import Country, Gauge, Team, Ticket, User


class Color(enum.Enum):
    RED = "r"


@pytest.mark.parametrize(
    ("field_type", "value", "expected"),
    [
        ("integer", 5, 5),
        ("integer", -(2**60), str(-(2**60))),
        ("float", 2, 2.0),
        ("float", float("inf"), None),
        ("decimal", Decimal("1.10"), "1.10"),
        ("decimal", 1.5, "1.5"),
        ("decimal", Decimal("NaN"), None),
        ("date", date(2026, 1, 2), "2026-01-02"),
        ("datetime", datetime(2026, 1, 2, 3, 4), "2026-01-02T03:04:00"),
        ("enum", Color.RED, "RED"),
        ("enum", "draft", "draft"),
        ("json", {"a": [1, None]}, {"a": [1, None]}),
        ("json", {"a": object()}, None),
        ("string", 12, "12"),
        ("uuid", uuid.UUID(int=1), "00000000-0000-0000-0000-000000000001"),
        ("boolean", False, False),
        ("unsupported", b"abcd", "<4 bytes>"),
        ("unsupported", memoryview(b"ab"), "<2 bytes>"),
        ("unsupported", "x" * 500, "x" * 199 + "…"),
        ("unsupported", 3.5, "3.5"),
        ("integer", None, None),
    ],
)
def test_encode_value(field_type: Any, value: object, expected: object) -> None:
    assert encode_value(field_type, value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1"),
        (uuid.UUID(int=2), "00000000-0000-0000-0000-000000000002"),
        (date(2026, 1, 2), "2026-01-02"),
    ],
)
def test_encode_pk(value: object, expected: str) -> None:
    assert encode_pk(value) == expected


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _reg(admin: Admin, model: type[Any], **options: Any) -> RegisteredModel:
    admin.register(type(f"{model.__name__}A", (ModelAdmin,), dict(options), model=model))
    return next(r for r in admin._registry if r.model is model)


@pytest.mark.parametrize(
    ("field_type", "raw", "expected"),
    [
        ("integer", "42", 42),
        ("integer", "-3", -3),
        ("integer", "abc", None),
        ("integer", "1.5", None),
        ("integer", "\u0663", None),
        ("integer", "9" * 25, None),
        ("integer", str(2**63), None),
        ("uuid", "00000000-0000-0000-0000-000000000009", uuid.UUID(int=9)),
        ("uuid", "not-a-uuid", None),
        ("decimal", "12.50", Decimal("12.50")),
        ("decimal", "NaN", None),
        ("decimal", "abc", None),
        ("date", "2026-01-02", date(2026, 1, 2)),
        ("date", "2026-13-01", None),
        ("datetime", "2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5)),
        ("string", "UZ", "UZ"),
        ("unsupported", "1", None),
    ],
)
def test_parse_key(field_type: str, raw: str, expected: object) -> None:
    assert parse_key(field_type, raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("32767", 32767), ("32768", None), ("-32768", -32768)]
)
def test_parse_key_respects_column_range(raw: str, expected: object) -> None:
    assert parse_key("integer", raw, low=-(2**15), high=2**15 - 1) == expected


def test_parse_pk_uses_registered_types(admin: Admin) -> None:
    assert parse_pk(_reg(admin, Country), "UZ") == "UZ"
    assert parse_pk(_reg(admin, User, exclude=["password_hash"]), str(2**31)) is None
    ticket = _reg(admin, Ticket)
    assert parse_pk(ticket, "00000000-0000-0000-0000-000000000009") == uuid.UUID(int=9)


@pytest.mark.parametrize(
    ("pk", "label", "expected"),
    [
        (1, None, "1"),
        (1, "", "1"),
        (1, "Core", "Core"),
        (1, "x" * 300, "x" * 199 + "\u2026"),
        (1, datetime(2026, 1, 2, 3, 4), "2026-01-02T03:04:00"),
        (1, 42, "42"),
    ],
)
def test_format_label(pk: object, label: object, expected: str) -> None:
    assert format_label(pk, label) == expected


def test_label_field_prefers_text_and_falls_back_to_pk(admin: Admin) -> None:
    assert label_field(_reg(admin, Team)) == "name"
    gauge = _reg(admin, Gauge, list_display=["id", "big"], exclude=["label"])
    assert label_field(gauge) == "id"


def test_nested_json_integers() -> None:
    assert encode_value("json", {"a": [2**60, True, 1.5]}) == {"a": [str(2**60), True, 1.5]}
