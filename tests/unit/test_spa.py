"""Unit tests for SPA serving helpers (`faststudio._spa`)."""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.types import Message, Scope

from faststudio import FastStudioError
from faststudio._spa import ADMIN_ROOT_KEY, AdminRootRecorder, SpaSite, render_index
from faststudio.config import Settings, resolve_settings


def _settings() -> Settings:
    return resolve_settings(
        secret_key=secrets.token_urlsafe(48),
        title="T",
        base_url="/admin",
        session_max_age=timedelta(hours=1),
        secure_cookies=True,
        max_page_size=100,
        max_list_offset=10_000,
        show_powered_by=True,
    )


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({"path": "/admin/models", "root_path": "/admin"}, "models"),
        ({"path": "/models", "root_path": ""}, "models"),
        ({"path": "/x/y", "root_path": "/other"}, "x/y"),
        ({"path": "/admin/assets/a.js", ADMIN_ROOT_KEY: "/admin"}, "assets/a.js"),
    ],
)
def test_route_path(tmp_path: Path, scope: dict[str, str], expected: str) -> None:
    request = Request({"type": "http", "headers": [], **scope})
    assert SpaSite(tmp_path, _settings()).route_path(request) == expected


def test_render_index_escapes_admin_root() -> None:
    html = render_index(
        "<!-- faststudio:head --><title>x</title>", admin_root='/a"b', title="T", max_list_offset=50
    )
    assert '<base href="/a&quot;b/">' in html


def test_rendered_cache_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!-- faststudio:head --><title>x</title>")
    site = SpaSite(tmp_path, _settings())
    for i in range(40):
        site.index_for(f"/p{i}/admin")
    assert len(site._rendered) == 16
    assert '<base href="/p39/admin/">' in site.index_for("/p39/admin")


def test_index_for_without_template_raises(tmp_path: Path) -> None:
    with pytest.raises(FastStudioError, match="not built"):
        SpaSite(tmp_path, _settings()).index_for("/admin")


async def test_root_recorder_ignores_non_http_scopes() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: object, send: object) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    scope: Scope = {"type": "lifespan"}
    await AdminRootRecorder(inner)(scope, receive, send)
    assert seen == ["lifespan"]
    assert ADMIN_ROOT_KEY not in scope
