"""Unit tests for list parameter parsing."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ModelAdmin
from faststudio.api.errors import ApiError
from faststudio.query._list import escape_like
from faststudio.query._params import (
    last_reachable_page,
    parse_choices_params,
    parse_list_params,
)
from faststudio.registry import RegisteredModel
from tests._stubs import StubAuthBackend
from tests.factories.models import AllTypes, Letter, Role

CAP = 10_000


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
    params = parse_list_params([(f"filter[{key}]", raw)], all_types, 100, max_list_offset=CAP)
    assert params.filters == {key: expected}


@pytest.mark.parametrize(
    ("key", "raw"),
    [("e_enum", "null"), ("e_strings", "Draft"), ("b_bool", "1"), ("e_letters", "1")],
)
def test_invalid_filter_values(all_types: RegisteredModel, key: str, raw: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        parse_list_params([(f"filter[{key}]", raw)], all_types, 100, max_list_offset=CAP)
    assert exc_info.value.code == "invalid_query"
    assert raw not in exc_info.value.message


def test_defaults(all_types: RegisteredModel) -> None:
    params = parse_list_params([], all_types, 100, max_list_offset=CAP)
    assert (params.page, params.page_size, params.q, params.filters) == (1, 25, None, {})


def test_choices_params() -> None:
    assert parse_choices_params([("page", "2"), ("q", " x ")], max_list_offset=CAP) == (2, "x")
    with pytest.raises(ApiError):
        parse_choices_params([("page_size", "5")], max_list_offset=CAP)


# A page is reachable iff its OFFSET, (page - 1) * page_size, is < max_list_offset.
# The SPA uses the same vectors (frontend/src/features/list/query.test.ts).
@pytest.mark.parametrize(
    ("cap", "page_size", "last"),
    [
        (10_000, 25, 400),
        (10_000, 30, 334),
        (10_000, 20, 500),
        (10_000, 100, 100),
        (100, 25, 4),
        (1, 25, 1),
        (10_000_000, 1, 10_000_000),
    ],
)
def test_last_reachable_page(cap: int, page_size: int, last: int) -> None:
    assert last_reachable_page(cap, page_size) == last
    assert (last - 1) * page_size < cap <= last * page_size


@pytest.mark.parametrize(("page_size", "last"), [(25, 400), (30, 334)])
def test_list_pages_stop_at_the_offset_cap(
    all_types: RegisteredModel, page_size: int, last: int
) -> None:
    def parse(page: int) -> int:
        items = [("page", str(page)), ("page_size", str(page_size))]
        return parse_list_params(items, all_types, 100, max_list_offset=CAP).page

    assert parse(last) == last  # offset 9_975 / 9_990 < 10_000
    with pytest.raises(ApiError) as exc_info:
        parse(last + 1)  # offset 10_000 / 10_020: not reachable
    error = exc_info.value
    assert (error.status_code, error.code) == (400, "invalid_query")
    assert "last reachable page" in error.message
    assert "search or filters" in error.message
    assert str(last + 1) not in error.message  # the submitted value is never echoed


def test_default_page_size_uses_the_models_setting(all_types: RegisteredModel) -> None:
    # all_types has page_size 25: page 400 is the last one under the default cap.
    assert parse_list_params([("page", "400")], all_types, 100, max_list_offset=CAP).page == 400
    with pytest.raises(ApiError):
        parse_list_params([("page", "401")], all_types, 100, max_list_offset=CAP)


def test_choices_pages_stop_at_the_offset_cap() -> None:
    assert parse_choices_params([("page", "500")], max_list_offset=CAP) == (500, None)
    with pytest.raises(ApiError) as exc_info:
        parse_choices_params([("page", "501")], max_list_offset=CAP)
    assert "last reachable page" in exc_info.value.message


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "1e3", "abc", "", "9999999999"])
def test_malformed_pages_are_rejected(all_types: RegisteredModel, raw: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        parse_list_params([("page", raw)], all_types, 100, max_list_offset=CAP)
    assert exc_info.value.message == "`page` must be a positive integer."


@pytest.mark.parametrize(
    ("text", "escaped"),
    [("100%", "100\\%"), ("a_b", "a\\_b"), ("c:\\x", "c:\\\\x"), ("plain", "plain")],
)
def test_escape_like(text: str, escaped: str) -> None:
    assert escape_like(text) == escaped
