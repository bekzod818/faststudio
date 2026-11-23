"""SPA serving, history fallback and runtime config injection (M5)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from faststudio import FastStudioError
from tests.integration.conftest import RENDERED_SCRIPT_CLOSINGS, AdminFactory


def _config(html: str) -> dict[str, object]:
    match = re.search(
        r'<script type="application/json" id="fs-config">(.*?)</script>', html, re.DOTALL
    )
    assert match, "fs-config block missing"
    data: dict[str, object] = json.loads(match.group(1))
    return data


# --------------------------------------------------------------------------- routing


async def test_root_without_slash_redirects(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    response = await client.get("/admin")
    assert response.status_code == 307
    assert response.headers["location"] == "/admin/"


async def test_redirect_keeps_query_string(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    response = await client.get("/admin?next=%2Fadmin%2Fmodels")
    assert response.headers["location"] == "/admin/?next=%2Fadmin%2Fmodels"


@pytest.mark.parametrize("path", ["/admin/", "/admin/models/users", "/admin/models/users/42/edit"])
async def test_history_fallback_serves_index(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str
) -> None:
    make_admin()
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<base href="/admin/">' in response.text
    assert '<div id="root"></div>' in response.text


async def test_head_request_on_spa_route(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    assert (await client.head("/admin/models/users")).status_code == 200


@pytest.mark.parametrize(
    "path", ["/admin/api", "/admin/api/", "/admin/api/v1/nope", "/admin/api/v1/"]
)
async def test_api_paths_never_fall_back_to_index(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str
) -> None:
    make_admin()
    response = await client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not found.", "details": None}
    }


async def test_unsafe_method_on_spa_route_is_405(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    response = await client.post("/admin/models/users")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["allow"] == "GET, HEAD"


async def test_admin_has_no_openapi_or_docs(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    for path in ("/admin/openapi.json", "/admin/docs", "/admin/redoc"):
        response = await client.get(path)
        assert response.headers["content-type"].startswith("text/html")
        assert 'id="fs-config"' in response.text  # the SPA shell, not generated docs


async def test_host_app_is_untouched(
    app: FastAPI, make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"hi": "there"}

    make_admin()
    response = await client.get("/hello")
    assert response.json() == {"hi": "there"}
    assert "content-security-policy" not in response.headers
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert all(not p.startswith("/admin") for p in paths)


# --------------------------------------------------------------------------- config injection


async def test_runtime_config_is_injected(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin(title="Back Office", base_url="/back-office/studio")
    response = await client.get("/back-office/studio/")
    assert '<base href="/back-office/studio/">' in response.text
    assert _config(response.text) == {
        "schema_version": "1",
        "base_url": "/back-office/studio",
        "api_url": "/back-office/studio/api/v1",
        "title": "Back Office",
    }
    assert "<title>Back Office</title>" in response.text


async def test_config_does_not_reveal_version(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    assert "version" not in _config((await client.get("/admin/")).text)


@pytest.mark.parametrize(
    "title",
    [
        "</script><script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "A & B <c>",
        "line\N{LINE SEPARATOR}sep\N{PARAGRAPH SEPARATOR}x",
    ],
)
async def test_title_cannot_break_out_of_html_or_json(
    make_admin: AdminFactory, client: httpx.AsyncClient, title: str
) -> None:
    make_admin(title=title)
    html = (await client.get("/admin/")).text
    assert "<script>alert" not in html
    assert "<img" not in html
    assert html.count("</script>") == RENDERED_SCRIPT_CLOSINGS
    block = html.split('id="fs-config">', 1)[1].split("</script>", 1)[0]
    assert "\N{LINE SEPARATOR}" not in block
    assert "\N{PARAGRAPH SEPARATOR}" not in block
    assert _config(html)["title"] == title


# --------------------------------------------------------------------------- reverse proxy


async def test_proxy_prefix_redirect_is_not_duplicated(
    make_admin: AdminFactory, proxy_client: httpx.AsyncClient
) -> None:
    make_admin()
    response = await proxy_client.get("/proxy/admin")
    assert response.status_code == 307
    assert response.headers["location"] == "/proxy/admin/"


async def test_proxy_prefix_is_rendered_into_the_shell(
    make_admin: AdminFactory, proxy_client: httpx.AsyncClient
) -> None:
    make_admin()
    html = (await proxy_client.get("/proxy/admin/models/users")).text
    assert '<base href="/proxy/admin/">' in html
    assert _config(html)["base_url"] == "/proxy/admin"
    assert _config(html)["api_url"] == "/proxy/admin/api/v1"


async def test_assets_and_api_work_behind_proxy_prefix(
    make_admin: AdminFactory, proxy_client: httpx.AsyncClient
) -> None:
    make_admin()
    asset = await proxy_client.get("/proxy/admin/assets/app.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    api = await proxy_client.get("/proxy/admin/api/v1/nope")
    assert api.status_code == 404
    assert api.headers["content-type"].startswith("application/json")


async def test_shell_rendered_per_mount_root(
    make_admin: AdminFactory, client: httpx.AsyncClient, proxy_client: httpx.AsyncClient
) -> None:
    make_admin()
    assert '<base href="/admin/">' in (await client.get("/admin/")).text
    assert '<base href="/proxy/admin/">' in (await proxy_client.get("/proxy/admin/")).text


# --------------------------------------------------------------------------- static files


async def test_assets_are_served(make_admin: AdminFactory, client: httpx.AsyncClient) -> None:
    make_admin()
    response = await client.get("/admin/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('fs');"


async def test_root_level_static_file_is_served(
    make_admin: AdminFactory, client: httpx.AsyncClient
) -> None:
    make_admin()
    response = await client.get("/admin/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"


@pytest.mark.parametrize("path", ["/admin/assets/missing.js", "/admin/assets/"])
async def test_missing_asset_is_json_404(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str
) -> None:
    make_admin()
    response = await client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/admin/assets/../../secret.txt",
        "/admin/assets/%2e%2e/%2e%2e/secret.txt",
        "/admin/..%2fsecret.txt",
        "/admin/%2e%2e/secret.txt",
        "/admin/assets/..%2f..%2fsecret.txt",
        "/admin/..%5csecret.txt",
    ],
)
async def test_path_traversal_never_reads_outside_static(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str
) -> None:
    make_admin()
    assert "TOP-SECRET" not in (await client.get(path)).text


@pytest.mark.parametrize(
    "path",
    [
        "/admin/index.html",
        "/admin/INDEX.HTML",
        "/admin/Index.Html",
        "/admin/index.html.",
        "/admin/index.html%20",
        "/admin/.hidden",
        "/admin/FAVICON.SVG",
    ],
)
async def test_root_files_are_exact_allowlist_matches(
    make_admin: AdminFactory, client: httpx.AsyncClient, static_dir: Path, path: str
) -> None:
    (static_dir / ".hidden").write_text("dot", encoding="utf-8")
    make_admin()
    response = await client.get(path)
    assert response.status_code == 200
    assert 'id="fs-config"' in response.text  # always the rendered shell
    assert "faststudio:head" not in response.text  # never the raw template
    assert response.text not in {"dot", "<svg/>"}


@pytest.mark.parametrize("path", ["/admin/x%00", "/admin/" + "a" * 300, "/admin/a%00.svg"])
async def test_unusual_names_never_error(
    make_admin: AdminFactory, client: httpx.AsyncClient, path: str
) -> None:
    make_admin()
    response = await client.get(path)
    assert response.status_code == 200
    assert 'id="fs-config"' in response.text


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
async def test_symlinks_in_static_root_are_not_served(
    make_admin: AdminFactory, client: httpx.AsyncClient, static_dir: Path
) -> None:
    (static_dir / "link.txt").symlink_to(static_dir.parent / "secret.txt")
    make_admin()
    assert "TOP-SECRET" not in (await client.get("/admin/link.txt")).text


# --------------------------------------------------------------------------- startup


async def test_unbuilt_spa_serves_placeholder(
    make_admin: AdminFactory, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    make_admin(static=tmp_path / "does-not-exist")
    response = await client.get("/admin/")
    assert response.status_code == 503
    assert "not built" in response.text
    assert "content-security-policy" in response.headers


def test_index_without_marker_fails_at_startup(make_admin: AdminFactory, static_dir: Path) -> None:
    (static_dir / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    with pytest.raises(FastStudioError, match="faststudio:head"):
        make_admin()
