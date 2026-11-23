"""Same-origin guard on the admin API, including reads (threat model T3)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tests.integration.conftest import AdminFactory


@pytest.fixture
def api_admin(make_admin: AdminFactory) -> None:
    admin = make_admin()

    async def data() -> dict[str, str]:
        return {"secret": "admin-data"}

    admin._sub_app.add_api_route("/api/v1/_data", data, methods=["GET", "POST"])


@pytest.mark.usefixtures("api_admin")
@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"origin": "http://testserver:8080"},
        {"origin": "https://testserver"},
        {"sec-fetch-site": "cross-site", "origin": "http://testserver"},
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_cross_origin_api_requests_are_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], method: str
) -> None:
    response = await client.request(method, "/admin/api/v1/_data", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert "admin-data" not in response.text


@pytest.mark.usefixtures("api_admin")
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"sec-fetch-site": "same-origin"},
        {"sec-fetch-site": "none"},
        {"origin": "http://testserver"},
        {"origin": "http://testserver:80"},
        {"sec-fetch-site": "same-origin", "origin": "https://evil.example"},
    ],
)
async def test_same_origin_and_non_browser_requests_pass(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/admin/api/v1/_data", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"secret": "admin-data"}


@pytest.mark.usefixtures("api_admin")
async def test_https_origin_with_default_port(https_client: httpx.AsyncClient) -> None:
    response = await https_client.get(
        "/admin/api/v1/_data", headers={"origin": "https://testserver:443"}
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("api_admin")
async def test_spa_shell_is_not_guarded(client: httpx.AsyncClient) -> None:
    response = await client.get("/admin/", headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 200  # navigation from another site is fine


async def test_permissive_host_cors_cannot_expose_admin_reads(
    app: FastAPI, make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    app.add_middleware(
        CORSMiddleware, allow_origin_regex=".*", allow_credentials=True, allow_methods=["*"]
    )
    admin = make_admin()

    async def data() -> dict[str, str]:
        return {"secret": "admin-data"}

    admin._sub_app.add_api_route("/api/v1/_data", data)
    response = await client.get(
        "/admin/api/v1/_data",
        headers={"origin": "https://evil.example", "cookie": "faststudio_session=x"},
    )
    assert response.status_code == 403
    assert "admin-data" not in response.text


async def test_missing_host_header_with_origin_is_rejected(
    make_admin: AdminFactory, app: FastAPI
) -> None:
    admin = make_admin()

    async def data() -> dict[str, str]:
        return {"secret": "admin-data"}

    admin._sub_app.add_api_route("/api/v1/_data", data)
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/admin/api/v1/_data",
        "raw_path": b"/admin/api/v1/_data",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"origin", b"http://testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1),
    }
    await app(scope, receive, send)  # type: ignore[arg-type]  # minimal hand-built scope
    assert sent[0]["status"] == 403
