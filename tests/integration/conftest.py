"""Fixtures for HTTP-level tests against a mounted FastStudio admin."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin
from tests._stubs import StubAuthBackend

FAKE_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <!-- faststudio:head -->
    <title>FastStudio</title>
    <script type="module" crossorigin src="./assets/app.js"></script>
    <link rel="stylesheet" href="./assets/app.css">
  </head>
  <body><div id="root"></div></body>
</html>
"""
#: `</script>` closings in a rendered shell: the template's own plus the config block.
RENDERED_SCRIPT_CLOSINGS = FAKE_INDEX.count("</script>") + 1


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(FAKE_INDEX, encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('fs');", encoding="utf-8")
    (static / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    return static


AdminFactory = Callable[..., Admin]


@pytest.fixture
def make_admin(  # noqa: PLR0917 - pytest fixtures
    app: FastAPI,
    engine: AsyncEngine,
    auth_backend: StubAuthBackend,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AdminFactory:
    def factory(**options: Any) -> Admin:
        monkeypatch.setattr("faststudio.admin._STATIC_DIR", options.pop("static", static_dir))
        return Admin(
            app, engine=engine, auth_backend=auth_backend, secret_key=secret_key, **options
        )

    return factory


def _client(
    app: FastAPI, *, base_url: str = "http://testserver", root_path: str = ""
) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, root_path=root_path)
    return httpx.AsyncClient(transport=transport, base_url=base_url)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        yield c


@pytest.fixture
async def proxy_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A server started with root_path="/proxy" (uvicorn --root-path), ASGI-spec paths."""
    async with _client(app, root_path="/proxy") as c:
        yield c


@pytest.fixture
async def https_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app, base_url="https://testserver") as c:
        yield c


async def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Headers carrying a valid anonymous CSRF token (cookie + header), as the SPA sends."""
    response = await client.get("/admin/")
    header = next(
        h for h in response.headers.get_list("set-cookie") if h.startswith("faststudio_csrftoken=")
    )
    token = header.split(";", 1)[0].split("=", 1)[1]
    return {"cookie": f"faststudio_csrftoken={token}", "x-faststudio-csrf": token}
