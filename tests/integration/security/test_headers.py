"""Security headers and cache policy on every admin response (threat model T6)."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI, Query

from tests.integration.conftest import AdminFactory

EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


def _assert_security_headers(response: httpx.Response) -> None:
    headers = response.headers
    assert headers["content-security-policy"] == EXPECTED_CSP
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "same-origin"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert "camera=()" in headers["permissions-policy"]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/admin/", 200),
        ("HEAD", "/admin/", 200),
        ("GET", "/admin/models/x", 200),
        ("GET", "/admin/assets/app.js", 200),
        ("GET", "/admin/assets/nope.js", 404),
        ("GET", "/admin/api/v1/nope", 404),
        ("POST", "/admin/", 405),
        ("GET", "/admin", 307),
    ],
)
async def test_headers_on_every_response(
    make_admin: AdminFactory, client: httpx.AsyncClient, method: str, path: str, status: int
) -> None:
    make_admin()
    response = await client.request(method, path)
    assert response.status_code == status
    _assert_security_headers(response)


@pytest.mark.parametrize(
    ("path", "cache"),
    [
        ("/admin/", "no-store"),
        ("/admin/api/v1/nope", "no-store"),
        ("/admin/assets/nope.js", "no-store"),
        ("/admin/assets/app.js", "public, max-age=31536000, immutable"),
        # SPA-fallback URLs merely *containing* the assets path stay uncacheable.
        ("/admin/x/admin/assets/app.js", "no-store"),
        ("/admin/models/assets/app.js", "no-store"),
    ],
)
async def test_cache_control(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str, cache: str
) -> None:
    make_admin()
    assert (await client.get(path)).headers["cache-control"] == cache


async def test_revalidated_and_partial_assets_stay_immutable(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    first = await client.get("/admin/assets/app.js")
    revalidated = await client.get(
        "/admin/assets/app.js", headers={"if-none-match": first.headers["etag"]}
    )
    assert revalidated.status_code == 304
    assert "immutable" in revalidated.headers["cache-control"]
    partial = await client.get("/admin/assets/app.js", headers={"range": "bytes=0-3"})
    assert partial.status_code == 206
    assert "immutable" in partial.headers["cache-control"]


async def test_hsts_only_over_https(
    make_admin: AdminFactory, client: httpx.AsyncClient, https_client: httpx.AsyncClient
) -> None:
    make_admin()
    assert "max-age=" in (await https_client.get("/admin/")).headers["strict-transport-security"]
    assert "strict-transport-security" not in (await client.get("/admin/")).headers


async def test_unhandled_error_is_generic_logged_and_has_headers(
    make_admin: AdminFactory, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    admin = make_admin()

    async def boom() -> None:
        msg = "db password=hunter2 leaked"
        raise RuntimeError(msg)

    admin._sub_app.add_api_route("/api/v1/_boom", boom)
    with caplog.at_level(logging.ERROR, logger="faststudio"):
        response = await client.get("/admin/api/v1/_boom?token=SECRET-QS")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error.", "details": None}
    }
    assert "hunter2" not in response.text
    _assert_security_headers(response)
    records = [r for r in caplog.records if r.name == "faststudio.api" and r.exc_info]
    assert records
    assert all("SECRET-QS" not in r.getMessage() for r in records)


async def test_host_exception_handler_still_sees_admin_failures(
    app: FastAPI, make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    seen: list[str] = []

    @app.exception_handler(Exception)
    async def host_handler(request: object, exc: Exception) -> None:
        seen.append(type(exc).__name__)

    admin = make_admin()

    async def boom() -> None:
        raise ValueError

    admin._sub_app.add_api_route("/api/v1/_boom", boom)
    response = await client.get("/admin/api/v1/_boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert seen == ["ValueError"]  # documented in ADR-0006: monitoring keeps working


async def test_request_validation_errors_use_contract_and_never_echo_input(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    admin = make_admin()

    async def needs_int(page: int = Query()) -> dict[str, int]:
        return {"page": page}

    admin._sub_app.add_api_route("/api/v1/_int", needs_int)
    response = await client.get("/admin/api/v1/_int", params={"page": "SECRET-INPUT"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    (issue,) = body["error"]["details"]
    assert issue["loc"] == ["query", "page"]
    assert issue["type"] == "int_parsing"
    assert set(issue) == {"loc", "msg", "type"}
    assert "SECRET-INPUT" not in response.text
    _assert_security_headers(response)
