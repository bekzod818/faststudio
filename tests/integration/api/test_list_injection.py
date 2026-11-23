"""Query allowlists: nothing outside ModelAdmin declarations reaches SQL (threat model T4)."""

from __future__ import annotations

import httpx
import pytest

USERS = "/admin/api/v1/models/users/items"


@pytest.mark.parametrize(
    "params",
    [
        {"ordering": "password_hash"},
        {"ordering": "-password_hash"},
        {"ordering": "full_name"},  # visible, but not sortable (not listed)
        {"ordering": "nope"},
        {"ordering": "email;DROP TABLE users"},
        {"ordering": "--id"},
        {"ordering": ""},
        {"ordering": "id,id"},
        {"ordering": "a,b,c,d,e,f"},
        {"filter[password_hash]": "x"},
        {"filter[email]": "user01@example.com"},
        {"filter[is_active]": "yes"},
        {"filter[is_active]": "null"},  # not nullable
        {"filter[role]": "admin"},
        {"filter[role]": "SUPERUSER"},
        {"filter[]": "x"},
        {"filter": "x"},
        {"page": "0"},
        {"page": "-1"},
        {"page": "abc"},
        {"page": "100001"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"page_size": "1e2"},
        {"q": "x" * 201},
        {"q": "a\x00b"},
        {"unknown": "1"},
        {"limit": "5"},
    ],
)
async def test_invalid_parameters_are_rejected(
    api: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await api.get(USERS, params=params)
    assert response.status_code == 400, (params, response.text)
    assert response.json()["error"]["code"] == "invalid_query"


@pytest.mark.parametrize("name", ["page", "q", "ordering", "filter[role]"])
async def test_repeated_parameters_are_rejected(api: httpx.AsyncClient, name: str) -> None:
    value = "ADMIN" if name.startswith("filter") else "1"
    response = await api.get(f"{USERS}?{name}={value}&{name}={value}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


async def test_error_does_not_echo_parameter_values(api: httpx.AsyncClient) -> None:
    response = await api.get(USERS, params={"ordering": "<script>SECRET</script>"})
    assert "SECRET" not in response.text
