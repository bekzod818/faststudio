"""Keep the user-facing docs honest: they must match the code."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import secrets
import sys
import types
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin
from faststudio.model_admin import OPTION_NAMES

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONFIGURATION = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
GETTING_STARTED = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
ICONS_TS = (ROOT / "frontend" / "src" / "app" / "icons.ts").read_text(encoding="utf-8")

# Admin(...) arguments that are wiring rather than settings.
_WIRING = {"app", "engine", "session_maker", "auth_backend"}
_ICON_NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"


def _table_names(text: str, header: str) -> set[str]:
    """Backticked names in the first column of the table under ``header``."""
    assert header in text, f"table header not found: {header!r}"
    table = text.split(header, 1)[1].split("\n\n", 1)[0]
    names: set[str] = set()
    for line in table.splitlines()[2:]:
        if not line.startswith("|"):
            continue
        names.update(re.findall(r"`([a-z0-9_]+)`", line.split("|")[1]))
    return names


def _admin_parameters() -> set[str]:
    return set(inspect.signature(Admin.__init__).parameters) - {"self"}


def test_configuration_reference_lists_every_admin_argument() -> None:
    documented = _table_names(CONFIGURATION, "| Option | Type | Default | Env var |")
    assert documented == _admin_parameters()


def test_readme_configuration_table_lists_every_setting() -> None:
    documented = _table_names(README, "| Option (`Admin(...)`) |")
    assert documented == _admin_parameters() - _WIRING


def test_configuration_reference_lists_every_model_admin_option() -> None:
    documented = _table_names(CONFIGURATION, "| Option | Default | Notes |")
    # `model` is the class keyword (`class UserAdmin(ModelAdmin, model=User)`).
    assert documented == set(OPTION_NAMES) - {"model"}
    assert "ModelAdmin, model=" in CONFIGURATION


def test_documented_icons_match_the_ui() -> None:
    in_ui = set(re.findall(rf'^\s+"?({_ICON_NAME})"?: [A-Z]', ICONS_TS, re.MULTILINE))
    assert "building-2" in in_ui  # names with digits are parsed too
    row = next(line for line in CONFIGURATION.splitlines() if line.startswith("| `icon` |"))
    assert set(re.findall(rf"`({_ICON_NAME})`", row)) - {"icon"} == in_ui


def test_readme_links_are_absolute() -> None:
    """PyPI renders the README outside the repository: relative links break."""
    patterns = [
        r"\]\(([^)]+)\)",  # [text](target)
        r'src="([^"]+)"',
        r'href="([^"]+)"',
        r"^\[[^\]]+\]:\s*(\S+)",  # [ref]: target
    ]
    targets = [t for pattern in patterns for t in re.findall(pattern, README, re.MULTILINE)]
    assert targets  # the patterns do match something
    assert [t for t in targets if not t.startswith(("https://", "#"))] == []


def _python_block_after(marker: str, text: str = README) -> str:
    assert marker in text, marker
    return text.split(marker, 1)[1].split("```python\n", 1)[1].split("```", 1)[0]


def test_getting_started_uses_the_tested_quickstart() -> None:
    marker = "Save as `main.py`"
    assert _python_block_after(marker, GETTING_STARTED) == _python_block_after(marker)
    command = "faststudio createadmin --app main:admin"
    assert command in README
    assert command in GETTING_STARTED


def _load_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> types.ModuleType:
    """Save main.py as the README says (a real `main` module); return it."""
    main_code = _python_block_after("Save as `main.py`")
    url = "sqlite+aiosqlite:///app.db"
    assert url in main_code
    main_code = main_code.replace(url, f"sqlite+aiosqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))

    # Real modules: SQLAlchemy resolves Mapped[...] and create_admin imports `main`.
    main = types.ModuleType("main")
    monkeypatch.setitem(sys.modules, "main", main)
    with caplog.at_level(logging.WARNING, logger="faststudio"):
        exec(compile(main_code, "README.md:main.py", "exec"), main.__dict__)
    assert caplog.records == []  # e.g. no "looks sensitive" or can_create warning
    return main


def _run_quickstart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> types.ModuleType:
    """Run the README steps: create_tables(), then ``faststudio createadmin``."""
    from faststudio import cli  # noqa: PLC0415

    main = _load_main(tmp_path, monkeypatch, caplog)
    asyncio.run(main.__dict__["create_tables"]())
    lines = iter(["admin", "admin@example.com"])  # username, then the email column
    passwords = iter(["a long passphrase", "a long passphrase"])
    out: list[str] = []
    io = cli.CliIO(
        read_line=lambda prompt: next(lines),
        read_password=lambda prompt: next(passwords),
        is_tty=lambda: True,
        write=out.append,
        error=out.append,
    )
    assert cli.main(["createadmin", "--app", "main:admin"], io=io) == 0, out
    return main


def _app_and_engine(main: types.ModuleType) -> tuple[FastAPI, AsyncEngine]:
    app, engine = main.__dict__["app"], main.__dict__["engine"]
    assert isinstance(app, FastAPI)
    assert isinstance(engine, AsyncEngine)
    return app, engine


def test_readme_quickstart_works_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Save main.py, run create_admin.py, start the app and sign in, as the README says."""
    app, engine = _app_and_engine(_run_quickstart(tmp_path, monkeypatch, caplog))
    asyncio.run(_sign_in_and_list_users(app, engine))


async def _sign_in_and_list_users(app: FastAPI, engine: AsyncEngine) -> None:
    origin = "https://testserver"
    try:
        transport = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
            await client.get("/admin/api/v1/auth/me")
            login = await client.post(
                "/admin/api/v1/auth/login",
                json={"username": "admin", "password": "a long passphrase"},
                headers={
                    "x-faststudio-csrf": client.cookies["faststudio_csrftoken"],
                    "origin": origin,
                },
            )
            assert login.status_code == 200, login.text
            users = (await client.get("/admin/api/v1/models/users/items")).json()
            assert [item["data"]["username"] for item in users["items"]] == ["admin"]
            assert "password_hash" not in users["items"][0]["data"]
    finally:
        await engine.dispose()


ORIGIN = "https://testserver"


async def _client_status(app: FastAPI, engine: AsyncEngine, password: str) -> tuple[int, int]:
    """Sign in as `admin` and try to drop the own admin flag: (login, PATCH) statuses."""
    try:
        transport = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            await client.get("/admin/api/v1/auth/me")
            login = await client.post(
                "/admin/api/v1/auth/login",
                json={"username": "admin", "password": password},
                headers={
                    "x-faststudio-csrf": client.cookies["faststudio_csrftoken"],
                    "origin": ORIGIN,
                },
            )
            if login.status_code != 200:
                return login.status_code, 0
            demote = await client.patch(
                "/admin/api/v1/models/users/items/1",
                json={"is_admin": False},
                headers={
                    "x-faststudio-csrf": client.cookies["faststudio_csrftoken"],
                    "origin": ORIGIN,
                },
            )
            assert (await client.get("/admin/api/v1/auth/me")).status_code == 200
            return login.status_code, demote.status_code
    finally:
        await engine.dispose()


async def _lock_out_in_the_database(engine: AsyncEngine) -> None:
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("UPDATE users SET is_admin = 0")
    finally:
        await engine.dispose()


def test_getting_started_lockout_guard_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The quickstart admin cannot demote themselves; restore_admin.py recovers a lockout."""
    main = _run_quickstart(tmp_path, monkeypatch, caplog)
    app, engine = _app_and_engine(main)
    assert asyncio.run(_client_status(app, engine, "a long passphrase")) == (200, 409)

    asyncio.run(_lock_out_in_the_database(engine))  # e.g. a manual database edit
    assert asyncio.run(_client_status(app, engine, "a long passphrase")) == (401, 0)

    restore_code = _python_block_after("Save as `restore_admin.py`", GETTING_STARTED)
    monkeypatch.setattr(sys, "argv", ["restore_admin.py", "admin"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a new long passphrase")
    exec(
        compile(restore_code, "getting-started.md:restore_admin.py", "exec"),
        {"__name__": "__main__"},
    )
    assert asyncio.run(_client_status(app, engine, "a new long passphrase")) == (200, 409)


def test_getting_started_without_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The v0.1 create_admin.py script, kept under "Without the CLI", still works."""
    main = _load_main(tmp_path, monkeypatch, caplog)
    admin_code = _python_block_after("Save as\n`create_admin.py`", GETTING_STARTED)
    answers = iter(["admin", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a long passphrase")
    exec(
        compile(admin_code, "getting-started.md:create_admin.py", "exec"), {"__name__": "__main__"}
    )
    app, engine = _app_and_engine(main)
    asyncio.run(_sign_in_and_list_users(app, engine))
