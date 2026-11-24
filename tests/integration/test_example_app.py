"""The example app (examples/basic) works end to end on the source tree."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from examples.basic.app import create_app
from examples.basic.db import PRODUCT_COUNT, create_or_update_admin

ORIGIN = "https://testserver"
USERNAME = "demo-admin"
PASSWORD = "a long demo passphrase"


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path}/example.db"


@asynccontextmanager
async def _started(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client,
    ):
        yield client


async def _sign_in(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    await client.get("/admin/api/v1/auth/me")
    token = client.cookies["faststudio_csrftoken"]
    return await client.post(
        "/admin/api/v1/auth/login",
        json={"username": USERNAME, "password": password},
        headers={"x-faststudio-csrf": token, "origin": ORIGIN},
    )


@pytest.mark.usefixtures("secret")
async def test_bootstrapped_admin_can_use_every_model(database_url: str) -> None:
    app = create_app(database_url, bootstrap_admin=(USERNAME, PASSWORD))
    async with _started(app) as client:
        assert (await client.get("/")).headers["location"] == "/admin/"
        assert (await _sign_in(client)).status_code == 200
        meta = (await client.get("/admin/api/v1/meta")).json()
        identities = [m["identity"] for m in meta["models"]]
        assert identities == ["users", "categories", "products", "tasks"]
        users = next(m for m in meta["models"] if m["identity"] == "users")
        assert "password_hash" not in {f["name"] for f in users["fields"]}
        assert users["permissions"]["create"] is False
        products = (await client.get("/admin/api/v1/models/products/items")).json()
        assert products["total"] == PRODUCT_COUNT
        assert products["items"][0]["labels"] == {"category_id": "Hardware"}

        token = client.cookies["faststudio_csrftoken"]
        headers = {"x-faststudio-csrf": token, "origin": ORIGIN}
        created = await client.post(
            "/admin/api/v1/models/tasks/items",
            json={"title": "Write docs", "category_id": 2},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        refused = await client.delete("/admin/api/v1/models/categories/items/1", headers=headers)
        assert refused.status_code == 409  # products still reference it


@pytest.mark.usefixtures("secret")
async def test_demo_data_is_seeded_once(database_url: str) -> None:
    for _ in range(2):
        app = create_app(database_url, bootstrap_admin=(USERNAME, PASSWORD))
        async with _started(app) as client:
            await _sign_in(client)
            total = (await client.get("/admin/api/v1/models/products/items")).json()["total"]
            assert total == PRODUCT_COUNT


@pytest.mark.usefixtures("secret")
async def test_without_bootstrap_nobody_can_sign_in(database_url: str) -> None:
    async with _started(create_app(database_url)) as client:
        assert (await _sign_in(client)).status_code == 401


@pytest.mark.parametrize(
    ("username", "message"),
    [
        ("", "empty"),
        (" admin", "spaces"),
        ("a" * 151, "at most 150"),
        ("ad\u202emin", "invalid characters"),
        ("ad\x00min", "invalid characters"),
    ],
)
async def test_create_admin_rejects_usernames_login_cannot_match(
    database_url: str, username: str, message: str
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415

    engine = create_async_engine(database_url)
    try:
        with pytest.raises(ValueError, match=message):
            await create_or_update_admin(async_sessionmaker(engine), username, PASSWORD)
    finally:
        await engine.dispose()


async def test_create_admin_rejects_short_passwords(database_url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415

    engine = create_async_engine(database_url)
    try:
        with pytest.raises(ValueError, match="at least 12"):
            await create_or_update_admin(async_sessionmaker(engine), USERNAME, "short")
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("secret")
async def test_demo_data_is_not_reinserted_into_a_used_database(database_url: str) -> None:
    """Products whose categories were all removed must not trigger a re-seed."""
    async with _started(create_app(database_url, bootstrap_admin=(USERNAME, PASSWORD))) as client:
        await _sign_in(client)
        headers = {"x-faststudio-csrf": client.cookies["faststudio_csrftoken"], "origin": ORIGIN}
        for pk in range(1, PRODUCT_COUNT + 1):
            response = await client.patch(
                f"/admin/api/v1/models/products/items/{pk}",
                json={"category_id": None},
                headers=headers,
            )
            assert response.status_code == 200
        for pk in (1, 2):
            response = await client.delete(
                f"/admin/api/v1/models/categories/items/{pk}", headers=headers
            )
            assert response.status_code == 204
    # Restarting must not try to insert products 1..30 again.
    async with _started(create_app(database_url, bootstrap_admin=(USERNAME, PASSWORD))) as client:
        await _sign_in(client)
        categories = (await client.get("/admin/api/v1/models/categories/items")).json()
        assert categories["total"] == 0


def test_module_has_no_import_side_effects() -> None:
    import examples.basic.app as module  # noqa: PLC0415

    assert not hasattr(module, "app")  # run with: uvicorn ...:create_app --factory


@pytest.mark.usefixtures("secret")
def test_main_runs_ephemeral_with_bootstrap_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    from examples.basic import __main__ as cli  # noqa: PLC0415

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **options: calls.append(options))
    monkeypatch.setenv("FASTSTUDIO_EXAMPLE_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD", PASSWORD)
    assert cli.main(["--ephemeral", "--port", "4321"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 4321, "log_level": "warning"}]


@pytest.mark.usefixtures("secret")
def test_main_warns_when_ephemeral_has_no_admin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.basic import __main__ as cli  # noqa: PLC0415

    monkeypatch.setattr("uvicorn.run", lambda app, **options: None)
    monkeypatch.delenv("FASTSTUDIO_EXAMPLE_ADMIN_USERNAME", raising=False)
    assert cli.main(["--ephemeral"]) == 0
    assert "nobody can sign in" in capsys.readouterr().err


def _answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    replies = iter(answers)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(replies))


def test_create_admin_cli(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.basic import create_admin  # noqa: PLC0415

    monkeypatch.setenv("FASTSTUDIO_EXAMPLE_DATABASE_URL", database_url)
    _answers(monkeypatch, PASSWORD, "different passphrase")
    assert create_admin.main([USERNAME]) == 1
    assert "do not match" in capsys.readouterr().err
    _answers(monkeypatch, "short", "short")
    assert create_admin.main([USERNAME]) == 1
    assert "at least 12" in capsys.readouterr().err
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert create_admin.main([USERNAME]) == 0
    assert "Created admin 'demo-admin'." in capsys.readouterr().out
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert create_admin.main([USERNAME]) == 0
    out = capsys.readouterr()
    assert "Updated admin" in out.out
    assert PASSWORD not in out.out + out.err  # never echoed


def test_create_admin_cli_reports_database_errors_without_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.basic import create_admin  # noqa: PLC0415

    # A corrupt file, not a missing directory: when aiosqlite fails to *connect*
    # it queues an unawaited stop on its worker thread, which can outlive
    # asyncio.run's loop and raise "Event loop is closed" (aiosqlite 0.22.1).
    # Here the connection opens and the first query fails, so dispose() closes it.
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not an SQLite database file" * 8)
    monkeypatch.setenv("FASTSTUDIO_EXAMPLE_DATABASE_URL", f"sqlite+aiosqlite:///{corrupt}")
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert create_admin.main([USERNAME]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "Could not save the admin (DatabaseError)."
    assert "not a database" not in err  # the driver's message stays hidden
