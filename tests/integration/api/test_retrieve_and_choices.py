"""GET one item and FK choices (M7)."""

from __future__ import annotations

import httpx
import pytest

from faststudio.schemas.contract import ChoicesResponse, Row

BASE = "/admin/api/v1/models"


async def test_retrieve_returns_all_visible_fields(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/users/items/7")
    assert response.status_code == 200
    row = Row.model_validate(response.json())
    assert row.pk == "7"
    assert row.data["bio"] == "likes 100% coverage"
    assert row.data["full_name"] == "User 07"
    assert row.data["created_at"] == "2026-01-08T12:00:00"
    assert row.labels == {"team_id": "Growth"}
    assert "password_hash" not in row.data
    assert "SECRET-HASH" not in response.text


@pytest.mark.parametrize(
    "pk",
    [
        "999",
        "abc",
        "1.5",
        "-",
        "1 OR 1=1",
        str(2**63),
        str(-(2**63) - 1),
        str(2**31),  # beyond the Integer column's 32-bit range
        "9" * 25,
        "\u0661",  # Arabic-Indic digit one: not an alias of /items/1
        "+1",
        " 1",
    ],
)
async def test_missing_or_malformed_pk_is_404(api: httpx.AsyncClient, pk: str) -> None:
    response = await api.get(f"{BASE}/users/items/{pk}")
    assert response.status_code == 404


async def test_retrieve_unknown_model_is_404(api: httpx.AsyncClient) -> None:
    assert (await api.get(f"{BASE}/nope/items/1")).status_code == 404


async def test_retrieve_encodes_special_types(api: httpx.AsyncClient) -> None:
    data = (await api.get(f"{BASE}/gauges/items/1")).json()["data"]
    assert data["token"] == "00000000-0000-0000-0000-000000000005"
    assert data["day"] == "2026-01-02"
    assert data["stamp"] == "2026-01-02T03:04:05"
    assert data["doc"] == {"k": [1, 2], "n": str(2**60)}
    assert data["blob"] == "<3 bytes>"
    assert data["flag"] is True


async def test_choices_for_registered_foreign_key(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/users/fields/team_id/choices")
    assert response.status_code == 200
    choices = ChoicesResponse.model_validate(response.json())
    assert choices.total == 3
    assert [(c.value, c.label) for c in choices.items] == [
        ("1", "Core"),
        ("2", "Growth"),
        ("3", "Ops"),
    ]


async def test_choices_search(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/users/fields/team_id/choices", params={"q": "gro"})
    assert [c["label"] for c in response.json()["items"]] == ["Growth"]


@pytest.mark.parametrize(
    "path",
    [
        "users/fields/email/choices",  # not a relation
        "users/fields/password_hash/choices",  # excluded
        "users/fields/nope/choices",
        "nope/fields/team_id/choices",
    ],
)
async def test_choices_only_for_visible_registered_relations(
    api: httpx.AsyncClient, path: str
) -> None:
    assert (await api.get(f"{BASE}/{path}")).status_code == 404


async def test_choices_for_fk_from_another_model(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/gauges/fields/team_id/choices")
    assert [c["label"] for c in response.json()["items"]] == ["Core", "Growth", "Ops"]


async def test_choices_for_joined_subclass_have_no_cartesian_rows(api: httpx.AsyncClient) -> None:
    """Label `kind` is on the base table; only the engineer row may appear, once."""
    response = await api.get(f"{BASE}/mentorships/fields/engineer_id/choices")
    assert response.json() == {"items": [{"value": "2", "label": "engineer"}], "total": 1}
    search = await api.get(f"{BASE}/mentorships/fields/engineer_id/choices", params={"q": "eng"})
    assert search.json()["total"] == 1  # searched on the label field (no search_fields)


async def test_choices_for_single_table_subclass_exclude_siblings(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/assignments/fields/employee_id/choices")
    assert response.json() == {"items": [{"value": "3", "label": "manager"}], "total": 1}


async def test_labels_never_come_from_sibling_subclasses(api: httpx.AsyncClient) -> None:
    rows = (await api.get(f"{BASE}/assignments/items")).json()["items"]
    assert [(r["pk"], r["labels"]) for r in rows] == [
        ("1", {}),  # points at an engineer: outside the registered `managers`
        ("2", {"employee_id": "manager"}),
    ]
    mentorship = (await api.get(f"{BASE}/mentorships/items/1")).json()
    assert mentorship["labels"] == {"engineer_id": "engineer"}


@pytest.mark.parametrize("params", [{"page": "0"}, {"q": "x" * 201}, {"other": "1"}])
async def test_choices_validate_parameters(api: httpx.AsyncClient, params: dict[str, str]) -> None:
    response = await api.get(f"{BASE}/users/fields/team_id/choices", params=params)
    assert response.status_code == 400


async def test_choices_reject_filter_parameters(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/users/fields/team_id/choices", params={"filter[x]": "1"})
    assert response.status_code == 400


async def test_choices_pagination(api: httpx.AsyncClient) -> None:
    response = await api.get(f"{BASE}/users/fields/team_id/choices", params={"page": "2"})
    assert response.json() == {"items": [], "total": 3}


async def test_choices_pages_stop_at_the_default_offset_cap(api: httpx.AsyncClient) -> None:
    url = "/admin/api/v1/models/users/fields/team_id/choices"
    assert (await api.get(url, params={"page": "500"})).status_code == 200  # offset 9 980
    refused = await api.get(url, params={"page": "501"})  # offset 10 000
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_query"
