"""Contract error format for all admin responses (M5)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from faststudio.api.errors import ApiError
from tests.integration.conftest import AdminFactory, csrf_headers


async def test_api_error_is_rendered_in_contract_format(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    admin = make_admin()

    async def limited() -> None:
        raise ApiError(429, "rate_limited", headers={"Retry-After": "30"})

    admin._sub_app.add_api_route("/api/v1/_limited", limited)
    response = await client.get("/admin/api/v1/_limited")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json() == {
        "error": {"code": "rate_limited", "message": "Too many requests.", "details": None}
    }


async def test_api_error_default_message(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    admin = make_admin()

    async def creds() -> None:
        raise ApiError(401, "invalid_credentials")

    admin._sub_app.add_api_route("/api/v1/_creds", creds)
    body = (await client.get("/admin/api/v1/_creds")).json()
    assert body["error"]["message"] == "Invalid username or password."


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_unknown_api_path_is_404_for_any_method(
    make_admin: AdminFactory, client: httpx.AsyncClient, method: str
) -> None:
    make_admin()
    response = await client.request(
        method, "/admin/api/v1/nope", headers=await csrf_headers(client)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_wrong_method_on_api_route_is_405(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    admin = make_admin()

    async def only_get() -> dict[str, bool]:
        return {"ok": True}

    admin._sub_app.add_api_route("/api/v1/_get", only_get, methods=["GET"])
    response = await client.delete("/admin/api/v1/_get", headers=await csrf_headers(client))
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(("status", "code"), [(418, "invalid_query"), (503, "internal_error")])
async def test_unmapped_http_statuses_get_generic_codes(
    make_admin: AdminFactory, client: httpx.AsyncClient, status: int, code: str
) -> None:
    admin = make_admin()

    async def odd() -> None:
        raise HTTPException(status, detail="internal detail must not leak")

    admin._sub_app.add_api_route("/api/v1/_odd", odd)
    response = await client.get("/admin/api/v1/_odd")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "internal detail" not in response.text


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


async def test_validation_loc_parts_are_truncated_and_bounded(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    admin = make_admin()

    async def create(body: _Strict) -> dict[str, str]:
        return {"name": body.name}

    admin._sub_app.add_api_route("/api/v1/_create", create, methods=["POST"])
    long_key = "<script>" + "k" * 500
    payload: dict[str, object] = {"name": "ok", long_key: "SECRET-VALUE"}
    payload.update({f"extra{i}": i for i in range(120)})
    response = await client.post(
        "/admin/api/v1/_create", json=payload, headers=await csrf_headers(client)
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert len(details) == 50
    assert all(len(str(part)) <= 64 for issue in details for part in issue["loc"])
    assert "SECRET-VALUE" not in response.text
    assert "k" * 100 not in response.text


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_unsafe_api_requests_without_csrf_are_rejected_before_routing(
    make_admin: AdminFactory, client: httpx.AsyncClient, method: str
) -> None:
    make_admin()
    response = await client.request(method, "/admin/api/v1/nope")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
