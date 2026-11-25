"""v0.1.0 apps keep working unchanged (v0.2 plan, hard constraint 1; M14).

`tests/compat/v0_1_0/` is a frozen copy of the v0.1.0 README and
`examples/basic` (see SNAPSHOT.md). These tests run that code, as released,
against the current FastStudio: every active admin keeps full access.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import sys
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

SNAPSHOT = Path(__file__).parent / "v0_1_0"
ORIGIN = "https://testserver"
API = "/admin/api/v1"


def test_snapshot_is_unchanged() -> None:
    """The snapshot must stay byte-identical to what SNAPSHOT.md recorded."""
    table = (SNAPSHOT / "SNAPSHOT.md").read_text(encoding="utf-8")
    recorded = dict(re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", table))
    assert set(recorded) == {
        "README.md",
        "basic/__init__.py",
        "basic/app.py",
        "basic/db.py",
        "basic/models.py",
    }
    for name, digest in recorded.items():
        assert hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest() == digest, name


# --------------------------------------------------------------------------- helpers


class _Session:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @property
    def headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.client.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def sign_in(self, username: str, password: str) -> int:
        await self.client.get(f"{API}/auth/me")
        response = await self.client.post(
            f"{API}/auth/login",
            json={"username": username, "password": password},
            headers=self.headers,
        )
        return response.status_code


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[_Session]:
    transport = httpx.ASGITransport(app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        yield _Session(client)


def _python_block_after(marker: str, text: str) -> str:
    assert marker in text, marker
    return text.split(marker, 1)[1].split("```python\n", 1)[1].split("```", 1)[0]


# --------------------------------------------------------------------------- README quickstart


def test_v0_1_0_readme_quickstart_runs_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readme = (SNAPSHOT / "README.md").read_text(encoding="utf-8")
    main_code = _python_block_after("Save as `main.py`", readme)
    admin_code = _python_block_after("Save as `create_admin.py`", readme)
    url = "sqlite+aiosqlite:///app.db"
    assert url in main_code
    main_code = main_code.replace(url, f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))

    main = types.ModuleType("main")
    monkeypatch.setitem(sys.modules, "main", main)
    exec(compile(main_code, "v0.1.0 README:main.py", "exec"), main.__dict__)
    answers = iter(["admin", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a long passphrase")
    exec(compile(admin_code, "v0.1.0 README:create_admin.py", "exec"), {"__name__": "__main__"})

    app, engine = main.__dict__["app"], main.__dict__["engine"]
    assert isinstance(app, FastAPI)
    assert isinstance(engine, AsyncEngine)
    asyncio.run(_quickstart_admin_has_full_access(app, engine))


async def _quickstart_admin_has_full_access(app: FastAPI, engine: AsyncEngine) -> None:
    try:
        async with _client(app) as s:
            assert await s.sign_in("admin", "a long passphrase") == 200
            meta = (await s.client.get(f"{API}/meta")).json()
            users = next(m for m in meta["models"] if m["identity"] == "users")
            # v0.1.0 semantics: only the static ModelAdmin flags limit an admin.
            assert {k: users["permissions"][k] for k in ("create", "edit", "delete")} == {
                "create": False,  # can_create = False in the v0.1.0 README
                "edit": True,
                "delete": True,
            }
            listed = (await s.client.get(f"{API}/models/users/items")).json()
            assert [item["data"]["username"] for item in listed["items"]] == ["admin"]
            assert "password_hash" not in str(listed)
            edited = await s.client.patch(
                f"{API}/models/users/items/1", json={"email": "new@example.com"}, headers=s.headers
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["data"]["email"] == "new@example.com"
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- examples/basic


@pytest.fixture
def example_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from tests.compat.v0_1_0.basic.app import create_app  # noqa: PLC0415

    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))
    app: FastAPI = create_app(
        f"sqlite+aiosqlite:///{tmp_path}/example.db",
        bootstrap_admin=("demo-admin", "a long demo passphrase"),
    )
    return app


async def test_v0_1_0_example_admin_has_full_access(example_app: FastAPI) -> None:
    from tests.compat.v0_1_0.basic.db import PRODUCT_COUNT  # noqa: PLC0415

    async with example_app.router.lifespan_context(example_app), _client(example_app) as s:
        assert await s.sign_in("demo-admin", "a long demo passphrase") == 200
        meta = (await s.client.get(f"{API}/meta")).json()
        identities = [m["identity"] for m in meta["models"]]
        assert identities == ["users", "categories", "products", "tasks"]
        tasks = next(m for m in meta["models"] if m["identity"] == "tasks")
        assert {k: tasks["permissions"][k] for k in ("create", "edit", "delete")} == {
            "create": True,
            "edit": True,
            "delete": True,
        }
        products = (await s.client.get(f"{API}/models/products/items")).json()
        assert products["total"] == PRODUCT_COUNT
        assert products["items"][0]["labels"] == {"category_id": "Hardware"}

        created = await s.client.post(
            f"{API}/models/tasks/items",
            json={"title": "Compat", "category_id": 2},
            headers=s.headers,
        )
        assert created.status_code == 201, created.text
        pk = created.json()["pk"]
        assert (await s.client.get(f"{API}/models/tasks/items/{pk}")).status_code == 200
        edited = await s.client.patch(
            f"{API}/models/tasks/items/{pk}", json={"title": "Compat 2"}, headers=s.headers
        )
        assert edited.status_code == 200, edited.text
        assert (
            await s.client.delete(f"{API}/models/tasks/items/{pk}", headers=s.headers)
        ).status_code == 204
        choices = await s.client.get(f"{API}/models/products/fields/category_id/choices")
        assert choices.status_code == 200
        refused = await s.client.delete(f"{API}/models/categories/items/1", headers=s.headers)
        assert refused.status_code == 409  # products still reference it, as in v0.1.0
