"""Unit tests for list parameter parsing."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ModelAdmin
from faststudio.api.errors import ApiError
from faststudio.query._list import escape_like
from faststudio.query._params import parse_choices_params, parse_list_params
from faststudio.registry import RegisteredModel
from tests._stubs import StubAuthBackend
from tests.factories.models import AllTypes, Letter, Role


@pytest.fixture
def all_types(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> RegisteredModel:
    admin = Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)
    admin.register(
        type(
            "A",
            (ModelAdmin,),
            {"list_filter": ["e_strings", "e_enum", "e_letters", "b_bool"], "can_create": False},
            model=AllTypes,
        )
    )
    return admin._registry.get("all_types")


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("e_strings", "draft", "draft"),
        ("e_strings", "null", None),
        ("e_enum", "EDITOR", Role.EDITOR),
        ("e_letters", "IN_PROGRESS", Letter.IN_PROGRESS),
        ("b_bool", "false", False),
    ],
)
def test_filter_values_are_converted(
    all_types: RegisteredModel, key: str, raw: str, expected: Any
) -> None:
    params = parse_list_params([(f"filter[{key}]", raw)], all_types, 100)
    assert params.filters == {key: expected}


@pytest.mark.parametrize(
    ("key", "raw"),
    [("e_enum", "null"), ("e_strings", "Draft"), ("b_bool", "1"), ("e_letters", "1")],
)
def test_invalid_filter_values(all_types: RegisteredModel, key: str, raw: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        parse_list_params([(f"filter[{key}]", raw)], all_types, 100)
    assert exc_info.value.code == "invalid_query"
    assert raw not in exc_info.value.message


def test_defaults(all_types: RegisteredModel) -> None:
    params = parse_list_params([], all_types, 100)
    assert (params.page, params.page_size, params.q, params.filters) == (1, 25, None, {})


def test_choices_params() -> None:
    assert parse_choices_params([("page", "2"), ("q", " x ")]) == (2, "x")
    with pytest.raises(ApiError):
        parse_choices_params([("page_size", "5")])


@pytest.mark.parametrize(
    ("text", "escaped"),
    [("100%", "100\\%"), ("a_b", "a\\_b"), ("c:\\x", "c:\\\\x"), ("plain", "plain")],
)
def test_escape_like(text: str, escaped: str) -> None:
    assert escape_like(text) == escaped
