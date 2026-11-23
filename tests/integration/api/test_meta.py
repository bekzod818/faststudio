"""GET /meta (M7)."""

from __future__ import annotations

import httpx
import pytest

import faststudio
from faststudio.schemas.contract import MetaResponse


async def test_meta_describes_registered_models(api: httpx.AsyncClient) -> None:
    response = await api.get("/admin/api/v1/meta")
    assert response.status_code == 200
    meta = MetaResponse.model_validate(response.json())
    assert meta.schema_version == "1"
    assert meta.version == faststudio.__version__
    assert meta.title == "FastStudio"
    assert meta.show_powered_by is True
    assert meta.user.username == "admin"
    assert [m.identity for m in meta.models][:3] == ["teams", "users", "gauges"]


async def test_meta_never_mentions_excluded_fields(api: httpx.AsyncClient) -> None:
    text = (await api.get("/admin/api/v1/meta")).text
    assert "password_hash" not in text


async def test_meta_resolves_relations(api: httpx.AsyncClient) -> None:
    meta = MetaResponse.model_validate((await api.get("/admin/api/v1/meta")).json())
    users = next(m for m in meta.models if m.identity == "users")
    team = next(f for f in users.fields if f.name == "team_id")
    assert team.relation is not None
    assert team.relation.target_identity == "teams"


@pytest.mark.usefixtures("admin")
@pytest.mark.parametrize(
    "path",
    [
        "/admin/api/v1/meta",
        "/admin/api/v1/models/users/items",
        "/admin/api/v1/models/users/items/1",
        "/admin/api/v1/models/users/fields/team_id/choices",
        "/admin/api/v1/models/nope/items",
    ],
)
async def test_read_routes_require_session(https_client: httpx.AsyncClient, path: str) -> None:
    response = await https_client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_relation_to_single_table_subclass_points_at_registered_subclass(
    api: httpx.AsyncClient,
) -> None:
    meta = MetaResponse.model_validate((await api.get("/admin/api/v1/meta")).json())
    assignments = next(m for m in meta.models if m.identity == "assignments")
    field = next(f for f in assignments.fields if f.name == "employee_id")
    assert field.relation is not None
    assert field.relation.target_identity == "managers"
