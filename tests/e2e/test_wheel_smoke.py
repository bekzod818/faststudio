"""Smoke tests that run against an *installed* wheel in a clean virtualenv.

CI sets FASTSTUDIO_WHEEL_SMOKE=1 after `pip install dist/*.whl`. Locally these
tests are skipped because the import would resolve to the source tree.
"""

import os
import re
import secrets
import sys
from importlib import resources
from pathlib import Path

import httpx
import pytest

import faststudio

# The example lives in the repository, not in the wheel: put the repo root on
# sys.path. `faststudio` still resolves to site-packages (src layout).
REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://testserver"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FASTSTUDIO_WHEEL_SMOKE") != "1",
        reason="set FASTSTUDIO_WHEEL_SMOKE=1 to run against an installed wheel",
    ),
]


def test_imports_from_site_packages() -> None:
    assert "site-packages" in Path(faststudio.__file__).parts


def test_spa_is_bundled() -> None:
    static = resources.files("faststudio") / "static"
    assert (static / "index.html").is_file()
    assert any(p.name.endswith(".js") for p in (static / "assets").iterdir())


def test_console_script_is_installed() -> None:
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    script = shutil.which("faststudio", path=str(Path(sys.executable).parent))
    assert script is not None
    result = subprocess.run(
        [script, "--help"], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "syncpermissions" in result.stdout


def test_typed_marker_is_bundled() -> None:
    assert (resources.files("faststudio") / "py.typed").is_file()


def test_example_app_runs_on_the_installed_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio  # noqa: PLC0415

    monkeypatch.syspath_prepend(str(REPO_ROOT))
    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))
    from examples.basic.app import create_app  # noqa: PLC0415

    assert "site-packages" in Path(sys.modules["faststudio"].__file__ or "").parts
    app = create_app(
        f"sqlite+aiosqlite:///{tmp_path}/smoke.db",
        bootstrap_admin=("smoke-admin", "smoke-test-passphrase"),
    )
    asyncio.run(_exercise(app))


async def _exercise(app: object) -> None:
    from fastapi import FastAPI  # noqa: PLC0415

    assert isinstance(app, FastAPI)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client,
    ):
        # The SPA shell and every asset it references come from the wheel.
        page = await client.get("/admin/")
        assert page.status_code == 200
        assert "script-src 'self'" in page.headers["content-security-policy"]
        # Resolved like a browser would, relative to the page URL.
        found = re.findall(r'(?:src|href)="([^"]*assets/[^"]+)"', page.text)
        assets = [httpx.URL(f"{ORIGIN}/admin/").join(ref).path for ref in found]
        assert any(asset.endswith(".js") for asset in assets)
        # Lazily loaded page chunks are referenced only from the main bundle:
        # fetch every file the wheel ships, not just what the page links.
        bundled = resources.files("faststudio") / "static" / "assets"
        names = sorted(entry.name for entry in bundled.iterdir())
        assert len([name for name in names if name.endswith(".js")]) > 1  # code splitting
        for asset in sorted({*assets, *(f"/admin/assets/{name}" for name in names)}):
            response = await client.get(asset)
            assert response.status_code == 200, asset
            assert "immutable" in response.headers["cache-control"]

        # Sign in and use the API: argon2, sessions and CSRF from the wheel.
        await client.get("/admin/api/v1/auth/me")
        headers = {"x-faststudio-csrf": client.cookies["faststudio_csrftoken"], "origin": ORIGIN}
        login = await client.post(
            "/admin/api/v1/auth/login",
            json={"username": "smoke-admin", "password": "smoke-test-passphrase"},
            headers=headers,
        )
        assert login.status_code == 200, login.text
        headers["x-faststudio-csrf"] = client.cookies["faststudio_csrftoken"]
        products = await client.get("/admin/api/v1/models/products/items")
        assert products.json()["total"] == 30
        created = await client.post(
            "/admin/api/v1/models/tasks/items", json={"title": "Smoke"}, headers=headers
        )
        assert created.status_code == 201, created.text
        pk = created.json()["pk"]
        deleted = await client.delete(f"/admin/api/v1/models/tasks/items/{pk}", headers=headers)
        assert deleted.status_code == 204


def test_installed_package_has_no_test_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scans of tests/unit/test_no_test_hooks.py, on the installed wheel (M20)."""
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    from tests.unit import test_no_test_hooks as scan  # noqa: PLC0415

    assert "site-packages" in scan.PACKAGE.parts
    scan.test_the_sources_are_scanned()
    scan.test_only_the_secret_key_is_read_from_the_environment()
    scan.test_sessions_always_use_the_real_clock()
