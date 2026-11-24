"""GET /models/{identity}/items: pagination, search, sort, filters (M7)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from faststudio.schemas.contract import ListResponse

USERS = "/admin/api/v1/models/users/items"


async def _list(api: httpx.AsyncClient, **params: Any) -> ListResponse:
    response = await api.get(USERS, params=params)
    assert response.status_code == 200, response.text
    return ListResponse.model_validate(response.json())


async def test_default_page(api: httpx.AsyncClient) -> None:
    page = await _list(api)
    assert (page.total, page.page, page.page_size) == (30, 1, 10)
    assert [row.pk for row in page.items] == [str(i) for i in range(1, 11)]
    first = page.items[0].data
    assert set(first) == {"id", "email", "is_active", "role", "team_id"}
    assert first["email"] == "user01@example.com"
    assert first["role"] == "EDITOR"


async def test_pagination(api: httpx.AsyncClient) -> None:
    page = await _list(api, page=3, page_size=7)
    assert [row.pk for row in page.items] == [str(i) for i in range(15, 22)]
    last = await _list(api, page=5, page_size=7)
    assert [row.pk for row in last.items] == ["29", "30"]
    beyond = await _list(api, page=9)
    assert beyond.items == []
    assert beyond.total == 30


async def test_relation_labels(api: httpx.AsyncClient) -> None:
    page = await _list(api, page_size=3)
    assert page.items[0].labels == {"team_id": "Growth"}  # user 1 -> team 2
    orphan = (await _list(api, page=30, page_size=1)).items[0]
    assert orphan.data["team_id"] is None
    assert orphan.labels == {}


@pytest.mark.parametrize(
    ("ordering", "first_pks"),
    [
        ("-id", ["30", "29", "28"]),
        ("email", ["1", "2", "3"]),
        ("-email", ["30", "29", "28"]),
        ("is_active,id", ["3", "6", "9"]),
        ("-is_active,-id", ["29", "28", "26"]),
    ],
)
async def test_ordering(api: httpx.AsyncClient, ordering: str, first_pks: list[str]) -> None:
    page = await _list(api, ordering=ordering, page_size=3)
    assert [row.pk for row in page.items] == first_pks


@pytest.mark.parametrize(
    ("q", "pks"),
    [
        ("user07", ["7"]),
        ("USER 1", [str(i) for i in range(10, 20)]),
        ("100%", ["7"]),
        ("%", ["7"]),
        ("_", ["8"]),
        ("under_score", ["8"]),
        ("nobody", []),
        ("' OR 1=1 --", []),
        ("\\", []),
    ],
)
async def test_search_is_literal_and_case_insensitive(
    api: httpx.AsyncClient, q: str, pks: list[str]
) -> None:
    page = await _list(api, q=q, page_size=50)
    assert [row.pk for row in page.items] == pks


async def test_empty_search_returns_everything(api: httpx.AsyncClient) -> None:
    assert (await _list(api, q="  ")).total == 30


@pytest.mark.parametrize(
    ("params", "total"),
    [
        ({"filter[is_active]": "true"}, 20),
        ({"filter[is_active]": "false"}, 10),
        ({"filter[role]": "ADMIN"}, 10),
        ({"filter[role]": "ADMIN", "filter[is_active]": "false"}, 10),
        ({"filter[role]": "EDITOR", "filter[is_active]": "false"}, 0),
        ({"filter[is_active]": "true", "q": "user0"}, 6),
    ],
)
async def test_filters(api: httpx.AsyncClient, params: dict[str, str], total: int) -> None:
    assert (await _list(api, page_size=50, **params)).total == total


async def test_excluded_fields_never_returned(api: httpx.AsyncClient) -> None:
    response = await api.get(USERS, params={"page_size": 50})
    assert "SECRET-HASH" not in response.text
    assert "password_hash" not in response.text


async def test_unknown_model_is_404(api: httpx.AsyncClient) -> None:
    response = await api.get("/admin/api/v1/models/nope/items")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_value_encoding(api: httpx.AsyncClient) -> None:
    response = await api.get("/admin/api/v1/models/gauges/items")
    row = response.json()["items"][0]["data"]
    assert row["big"] == str(2**60)  # beyond JavaScript's safe integers
    assert row["ratio"] is None  # NaN is not JSON
    assert row["amount"] == "12.50"
    assert row["role"] == "ADMIN"


async def test_large_integers_nested_in_json_are_strings(api: httpx.AsyncClient) -> None:
    data = (await api.get("/admin/api/v1/models/gauges/items/1")).json()["data"]
    assert data["doc"] == {"k": [1, 2], "n": str(2**60)}


async def test_inheritance_lists_only_own_rows(api: httpx.AsyncClient) -> None:
    managers = (await api.get("/admin/api/v1/models/managers/items")).json()
    assert [row["pk"] for row in managers["items"]] == ["3"]
    assert managers["total"] == 1
    engineers = (await api.get("/admin/api/v1/models/engineers/items")).json()
    assert [(r["pk"], r["data"]["kind"]) for r in engineers["items"]] == [("2", "engineer")]


@pytest.mark.parametrize(
    ("params", "total"),
    [
        ({"filter[role]": "null"}, 0),
        ({"filter[role]": "ADMIN"}, 1),
        ({"filter[flag]": "null"}, 0),
        ({"filter[flag]": "true"}, 1),
    ],
)
async def test_filters_on_nullable_fields(
    api: httpx.AsyncClient, params: dict[str, str], total: int
) -> None:
    response = await api.get("/admin/api/v1/models/gauges/items", params=params)
    assert response.json()["total"] == total


async def test_list_without_relations_has_no_labels(api: httpx.AsyncClient) -> None:
    page = (await api.get("/admin/api/v1/models/teams/items")).json()
    assert all(item["labels"] == {} for item in page["items"])


# --------------------------------------------------------------------------- offset cap
# A page is reachable iff (page - 1) * page_size < max_list_offset (default 10 000).


@pytest.mark.parametrize(("page_size", "last"), [(10, 1000), (25, 400), (30, 334)])
async def test_pages_stop_at_the_default_offset_cap(
    api: httpx.AsyncClient, page_size: int, last: int
) -> None:
    ok = await api.get(USERS, params={"page": last, "page_size": page_size})
    assert ok.status_code == 200
    assert ok.json()["items"] == []  # reachable, just past the 30 seeded rows
    refused = await api.get(USERS, params={"page": last + 1, "page_size": page_size})
    assert refused.status_code == 400
    error = refused.json()["error"]
    assert error["code"] == "invalid_query"
    assert "last reachable page" in error["message"]


@pytest.mark.parametrize("admin_options", [{"max_list_offset": 25}])
async def test_offset_cap_is_configurable(api: httpx.AsyncClient) -> None:
    # users: page_size 10, cap 25 -> offsets 0, 10, 20 are reachable (pages 1-3).
    assert (await api.get(USERS, params={"page": 3})).json()["items"][0]["pk"] == "21"
    assert (await api.get(USERS, params={"page": 4})).status_code == 400
    choices = "/admin/api/v1/models/users/fields/team_id/choices"
    assert (await api.get(choices, params={"page": 2})).status_code == 200  # offset 20 < 25
    assert (await api.get(choices, params={"page": 3})).status_code == 400  # offset 40
