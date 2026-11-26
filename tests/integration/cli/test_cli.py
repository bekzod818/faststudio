"""The ``faststudio`` CLI (ADR-0012, M19), on SQLite and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from faststudio import hash_password
from faststudio.auth.passwords import verify_password_async
from faststudio.cli import main
from tests._databases import MYSQL_URL, mysql_param, throwaway
from tests.factories.contrib_models import AUTH, ContribBase
from tests.integration.cli import apps
from tests.integration.cli.conftest import FakeTerminal

POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
GOOD = "a long new passphrase"
APP = "tests.integration.cli.apps"


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
            ],
        ),
        mysql_param("mysql"),
    ]
)
def url(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "postgres":
        assert (make_url(POSTGRES_URL).database or "").endswith("_test")
        value = POSTGRES_URL
    elif request.param == "mysql":
        value = throwaway(MYSQL_URL)
    else:
        value = f"sqlite+aiosqlite:///{tmp_path}/cli.db"
    monkeypatch.setattr(apps, "DATABASE_URL", value)
    return value


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for metadata in (ContribBase.metadata, apps.HostBase.metadata):
                await conn.run_sync(metadata.drop_all)
                await conn.run_sync(metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture
def db(url: str) -> Iterator[str]:
    _run(_reset(url))
    yield url
    _run(_drop(url))


async def _drop(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for metadata in (ContribBase.metadata, apps.HostBase.metadata):
                await conn.run_sync(metadata.drop_all)
    finally:
        await engine.dispose()


async def _query(url: str, statement: Any) -> list[Any]:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            return list((await session.execute(statement)).all())
    finally:
        await engine.dispose()


def cli(terminal: FakeTerminal, *argv: str) -> int:
    return main(list(argv), io=terminal.io())


# --------------------------------------------------------------------------- usage


@pytest.mark.parametrize(
    ("argv", "code", "message"),
    [
        (["createadmin", "--app", "nocolon"], 2, "module.path:attr"),
        (["createadmin", "--app", "no_such_module_xyz:admin"], 2, "Cannot import"),
        (["createadmin", "--app", f"{APP}:missing"], 2, "has no attribute"),
        (["createadmin", "--app", f"{APP}:not_an_admin"], 2, "is not a faststudio.Admin"),
        (["createadmin", "--app", f"{APP}:fastapi_app"], 2, "has no faststudio.Admin mounted"),
        (["createadmin", "--app", f"{APP}:no_admin_app"], 2, "has no faststudio.Admin mounted"),
        (["createadmin", "--app", f"{APP}:not_an_app"], 2, "returned dict"),
        (["createadmin", "--app", f"{APP}:needs_arguments"], 2, "a factory of one"),
        (["createadmin", "--app", f"{APP}:builtin_factory"], 2, "returned dict"),
    ],
)
def test_app_resolution_errors(
    terminal: FakeTerminal, url: str, argv: list[str], code: int, message: str
) -> None:
    assert cli(terminal, *argv) == code
    assert message in terminal.text


def test_several_mounted_admins_are_listed(terminal: FakeTerminal, url: str) -> None:
    assert cli(terminal, "createadmin", "--app", f"{APP}:two_admins_app") == 2
    assert "2 faststudio.Admin instances are mounted" in terminal.text
    assert "/admin" in terminal.text
    assert "/staff" in terminal.text
    assert "point --app at the one you mean" in terminal.text


def test_a_type_error_inside_a_factory_is_not_called_a_bad_target(
    terminal: FakeTerminal, url: str
) -> None:
    assert cli(terminal, "createadmin", "--app", f"{APP}:buggy_factory") == 2
    assert terminal.err == [f"Calling {APP}:buggy_factory() failed (TypeError)."]


@pytest.mark.usefixtures("db")
@pytest.mark.parametrize(
    "target",
    [
        "host_app",
        "mounted_app",
        "nested_app",
        "wrapped_nested_app",
        "router_mounted_app",
        "cyclic_app",
    ],
)
def test_a_fastapi_app_or_factory_is_an_app_target(
    terminal: FakeTerminal, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """The application (or its factory) is enough when exactly one Admin is mounted."""
    monkeypatch.setattr(apps, "mounted_app", apps.host_app())
    terminal.passwords = [GOOD, GOOD]
    assert cli(terminal, "createadmin", "--app", f"{APP}:{target}", "--username", "ann") == 0
    assert "Created admin 'ann'" in terminal.text
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:{target}", "--dry-run") == 0


def test_argparse_errors_and_help(
    terminal: FakeTerminal, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(terminal) == 2
    assert cli(terminal, "createadmin") == 2  # --app is required
    assert cli(terminal, "--help") == 0
    assert "syncpermissions" in capsys.readouterr().out


def test_backends_without_accounts(terminal: FakeTerminal, db: str) -> None:
    assert cli(terminal, "createadmin", "--app", f"{APP}:no_accounts", "--username", "x") == 1
    assert "no `accounts` capability" in terminal.text
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:no_accounts") == 1
    assert "no `permission_schema`" in terminal.text
    assert cli(terminal, "checkusers", "--app", f"{APP}:no_accounts") == 1
    assert "no `username_audit` capability" in terminal.text


def test_missing_tables_give_the_migration_hint(terminal: FakeTerminal, url: str) -> None:
    _run(_drop(url))
    terminal.passwords = [GOOD, GOOD]
    assert cli(terminal, "createadmin", "--app", f"{APP}:contrib", "--username", "ann") == 1
    assert "run your migrations" in terminal.text
    assert "SELECT" not in terminal.text  # no SQL or internals


# --------------------------------------------------------------------------- createadmin


def test_createadmin_model_user_backend_prompts_required_columns(
    terminal: FakeTerminal, db: str
) -> None:
    terminal.lines = ["ann", "ann@example.com"]  # username, then the email column
    terminal.passwords = [GOOD, GOOD]
    assert cli(terminal, "createadmin", "--app", f"{APP}:model_users") == 0, terminal.text
    rows = _run(_query(db, select(apps.Staff)))
    staff = rows[0][0]
    assert (staff.username, staff.email, staff.is_active, staff.is_admin) == (
        "ann",
        "ann@example.com",
        True,
        True,
    )
    assert _run(verify_password_async(staff.password_hash, GOOD))
    assert GOOD not in terminal.text
    assert "$argon2" not in terminal.text


def test_createadmin_with_set_and_no_terminal_input(terminal: FakeTerminal, db: str) -> None:
    terminal.tty = False
    argv = ["createadmin", "--app", f"{APP}:model_users", "--username", "bob"]
    assert cli(terminal, *argv) == 1  # email is required and no terminal to ask
    assert "Missing required value(s): email" in terminal.text
    assert cli(terminal, *argv, "--set", "email=bob@example.com") == 2  # password needs a TTY
    assert "needs an interactive terminal" in terminal.text
    assert _run(_query(db, select(apps.Staff))) == []


@pytest.mark.parametrize(
    ("argv", "code", "message"),
    [
        (["--set", "email"], 2, "FIELD=VALUE"),
        (["--set", "email=x", "--set", "shoe_size=42"], 1, "Not a text column"),
        (["--set", "email=x", "--set", "password_hash=x"], 1, "Not a text column"),
    ],
)
def test_createadmin_set_validation(
    terminal: FakeTerminal, db: str, argv: list[str], code: int, message: str
) -> None:
    terminal.passwords = [GOOD, GOOD]
    full = ["createadmin", "--app", f"{APP}:model_users", "--username", "cy", *argv]
    assert cli(terminal, *full) == code
    assert message in terminal.text


@pytest.mark.parametrize(
    ("passwords", "message"),
    [
        ([GOOD, GOOD + "x"], "The passwords do not match."),
        (["short", "short"], "Use at least 12 characters."),
        (["dan-the-admin-1", "dan-the-admin-1"], "less similar"),
    ],
)
def test_createadmin_password_rules(
    terminal: FakeTerminal, db: str, passwords: list[str], message: str
) -> None:
    terminal.passwords = list(passwords)  # the parameter is shared between databases
    argv = ["createadmin", "--app", f"{APP}:contrib", "--username", "dan"]
    assert cli(terminal, *argv) == 1
    assert message in terminal.text
    for secret in passwords:
        assert secret not in terminal.text


@pytest.mark.parametrize("username", ["", " padded", "x" * 151, "bad\u202ename"])
def test_createadmin_username_rules(terminal: FakeTerminal, db: str, username: str) -> None:
    argv = ["createadmin", "--app", f"{APP}:contrib", "--username", username]
    assert cli(terminal, *argv) == 1


def test_createadmin_contrib_makes_a_superuser(terminal: FakeTerminal, db: str) -> None:
    terminal.passwords = [GOOD, GOOD]
    argv = ["createadmin", "--app", f"{APP}:contrib", "--username", "Root", "--set", "email=r@x.io"]
    assert cli(terminal, *argv) == 0, terminal.text
    rows = _run(_query(db, select(AUTH.user)))
    root = rows[0][0]
    assert (root.username_normalized, root.is_superuser, root.is_active, root.email) == (
        "root",
        True,
        True,
        "r@x.io",
    )
    # An existing account (any case) is refused: use changepassword.
    assert cli(terminal, "createadmin", "--app", f"{APP}:contrib", "--username", "ROOT") == 1
    assert "already exists" in terminal.text
    terminal.passwords = [GOOD, GOOD]
    bad = ["createadmin", "--app", f"{APP}:contrib", "--username", "x2", "--set", "phone=1"]
    assert cli(terminal, *bad) == 1
    assert "only email can be set" in terminal.text


def test_createadmin_asks_the_username_only_on_a_terminal(terminal: FakeTerminal, db: str) -> None:
    terminal.tty = False
    assert cli(terminal, "createadmin", "--app", f"{APP}:contrib") == 2
    assert "pass --username" in terminal.text


# --------------------------------------------------------------------------- changepassword


def test_changepassword(terminal: FakeTerminal, db: str) -> None:
    async def seed() -> None:
        engine = create_async_engine(db)
        async with AsyncSession(engine) as session:
            session.add(AUTH.user(username="Eve", password_hash=hash_password("the old one 12")))
            await session.commit()
        await engine.dispose()

    _run(seed())
    terminal.passwords = [GOOD, GOOD]
    assert cli(terminal, "changepassword", "eve", "--app", f"{APP}:contrib") == 0, terminal.text
    eve = _run(_query(db, select(AUTH.user)))[0][0]
    assert _run(verify_password_async(eve.password_hash, GOOD))
    assert cli(terminal, "changepassword", "nobody", "--app", f"{APP}:contrib") == 1
    assert "No account named 'nobody'" in terminal.text
    terminal.tty = False
    assert cli(terminal, "changepassword", "eve", "--app", f"{APP}:contrib") == 2


# --------------------------------------------------------------------------- syncpermissions


def _codenames(db: str) -> dict[str, str]:
    rows = _run(_query(db, select(AUTH.permission.codename, AUTH.permission.name)))
    return dict(rows)


def test_syncpermissions_is_idempotent_and_names_permissions(
    terminal: FakeTerminal, db: str
) -> None:
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--dry-run") == 0
    assert "Dry run" in terminal.text
    assert _codenames(db) == {}
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib") == 0, terminal.text
    stored = _codenames(db)
    assert stored["notes.view"] == "Can view notes"
    assert stored["notes.publish"] == "Publish notes"
    assert "faststudio_user.edit" in stored
    assert len(stored) == 4 * 4 + 1  # users, groups, permissions, notes + publish
    terminal.out.clear()
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib") == 0
    assert "Created 0, renamed 0 permission(s)." in terminal.text


def test_syncpermissions_updates_names_and_prunes_only_when_asked(
    terminal: FakeTerminal, db: str
) -> None:
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib") == 0

    async def drift() -> None:
        engine = create_async_engine(db)
        async with engine.begin() as conn:
            await conn.execute(
                AUTH.permission.__table__.update()  # type: ignore[attr-defined]
                .where(AUTH.permission.codename == "notes.view")
                .values(name="old name")
            )
            await conn.execute(
                insert(AUTH.permission.__table__),  # type: ignore[attr-defined]
                [{"id": 900, "codename": "oldnotes.view"}, {"id": 901, "codename": "gone.edit"}],
            )
            await conn.execute(insert(AUTH.group.__table__), [{"id": 1, "name": "g"}])  # type: ignore[attr-defined]
            await conn.execute(
                insert(AUTH.group_permissions), [{"group_id": 1, "permission_id": 900}]
            )
        await engine.dispose()

    _run(drift())
    terminal.out.clear()
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--dry-run") == 0
    assert "Renamed (1):" in terminal.text
    assert "Stale (no registered model produces them) (2):" in terminal.text
    assert "Orphaned (stale, still granted) (1):" in terminal.text
    assert "  oldnotes.view" in terminal.text
    assert _codenames(db)["notes.view"] == "old name"  # dry run wrote nothing

    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib") == 0  # no --prune
    assert set(_codenames(db)) >= {"oldnotes.view", "gone.edit"}
    assert _codenames(db)["notes.view"] == "Can view notes"

    terminal.tty = False  # --prune without a terminal and without --yes: refused
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--prune") == 2
    terminal.tty = True
    terminal.lines = ["n"]
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--prune") == 1
    assert "oldnotes.view" in _codenames(db)
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--prune", "--yes") == 0
    assert not {"oldnotes.view", "gone.edit"} & set(_codenames(db))
    assert _run(_query(db, select(AUTH.group_permissions))) == []  # their grants too


def test_concurrent_syncs_tolerate_each_other(terminal: FakeTerminal, db: str) -> None:
    from faststudio.api._permission_sync import apply_sync, plan_sync  # noqa: PLC0415
    from faststudio.cli._app import load_admin  # noqa: PLC0415

    async def both() -> None:
        admin = load_admin(f"{APP}:contrib")
        rules, registry, maker = admin._escalation, admin._registry, admin._session_maker
        assert rules is not None
        async with maker() as first, maker() as second:
            plan_a = await plan_sync(first, rules, registry)
            plan_b = await plan_sync(second, rules, registry)
            async with first.begin_nested():
                await apply_sync(first, rules, plan_a, prune=False)
            await first.commit()
            await apply_sync(second, rules, plan_b, prune=False)  # every insert collides
            await second.commit()
        await maker.kw["bind"].dispose()

    _run(both())
    assert len(_codenames(db)) == 17


# --------------------------------------------------------------------------- checkusers


def _check_mysql_refuses_collisions(terminal: FakeTerminal, db: str) -> None:
    """MySQL's default collation (utf8mb4_0900_ai_ci) already treats 'Ann' and 'ANN'
    (and full-width or ligature forms) as equal: the unique username index refuses
    the collision itself, so only drift is left for checkusers to repair."""
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    table = AUTH.user.__table__  # type: ignore[attr-defined]

    def row(pk: int, username: str, normalized: str) -> dict[str, object]:
        return {
            "id": pk,
            "username": username,
            "username_normalized": normalized,
            "password_hash": "!",
            "session_token": str(pk) * 43,
        }

    async def seed() -> None:
        engine = create_async_engine(db)
        try:
            async with engine.begin() as conn:
                await conn.execute(insert(table), [row(1, "Ann", "ann"), row(2, "Bob", "stale")])
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(table), [row(3, "ANN", "ann-old")])
        finally:
            await engine.dispose()

    _run(seed())
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib") == 1
    assert "Stale normalized username: 'Bob' (id 2)" in terminal.text
    assert "Collision" not in terminal.text
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib", "--fix", "--yes") == 0
    rows = dict(_run(_query(db, select(AUTH.user.id, AUTH.user.username_normalized))))
    assert rows == {1: "ann", 2: "bob"}


def test_checkusers_reports_fixes_and_refuses_collisions(terminal: FakeTerminal, db: str) -> None:
    async def seed() -> None:
        engine = create_async_engine(db)
        async with engine.begin() as conn:
            table = AUTH.user.__table__  # type: ignore[attr-defined]
            await conn.execute(  # Core inserts bypass the ORM: drift on purpose
                insert(table),
                [
                    {
                        "id": 1,
                        "username": "Ann",
                        "username_normalized": "ann",
                        "password_hash": "!",
                        "session_token": "a" * 43,
                    },
                    {
                        "id": 2,
                        "username": "Bob",
                        "username_normalized": "stale",
                        "password_hash": "!",
                        "session_token": "b" * 43,
                    },
                    {
                        "id": 3,
                        "username": "ANN",
                        "username_normalized": "ann-old",
                        "password_hash": "!",
                        "session_token": "c" * 43,
                    },
                ],
            )
        await engine.dispose()

    if db.startswith("mysql"):
        _check_mysql_refuses_collisions(terminal, db)
        return
    _run(seed())
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib") == 1
    assert "Collision on 'ann'" in terminal.text
    assert "Stale normalized username: 'Bob' (id 2)" in terminal.text
    assert "'ANN' (id 3) (collides: fix by renaming)" in terminal.text

    terminal.tty = False
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib", "--fix") == 2
    terminal.tty = True
    terminal.lines = ["no"]
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib", "--fix") == 1
    assert (
        cli(terminal, "checkusers", "--app", f"{APP}:contrib", "--fix", "--yes") == 1
    )  # collision
    rows = dict(_run(_query(db, select(AUTH.user.id, AUTH.user.username_normalized))))
    assert rows == {1: "ann", 2: "bob", 3: "ann-old"}  # Bob fixed; the collision untouched

    async def rename() -> None:
        engine = create_async_engine(db)
        async with AsyncSession(engine) as session:
            user = await session.get(AUTH.user, 3)
            assert user is not None
            user.username = "Ann2"
            await session.commit()
        await engine.dispose()

    _run(rename())
    terminal.out.clear()
    assert cli(terminal, "checkusers", "--app", f"{APP}:contrib") == 0
    assert "All usernames are consistent." in terminal.text


# --------------------------------------------------------------------------- edges


def test_changepassword_when_the_account_vanishes(
    terminal: FakeTerminal, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from faststudio.contrib.auth import DatabaseAuthBackend  # noqa: PLC0415

    terminal.passwords = [GOOD, GOOD]
    terminal.lines = []
    _run(_seed_user(db, "fay"))

    async def gone(self: object, session: object, account_id: str, password: str) -> None:
        raise LookupError(account_id)

    monkeypatch.setattr(DatabaseAuthBackend, "set_password", gone)
    assert cli(terminal, "changepassword", "fay", "--app", f"{APP}:contrib") == 1
    assert "No account named 'fay'" in terminal.text


async def _seed_user(db: str, username: str) -> None:
    engine = create_async_engine(db)
    async with AsyncSession(engine) as session:
        session.add(AUTH.user(username=username, password_hash=hash_password("seeded passphrase")))
        await session.commit()
    await engine.dispose()


def test_other_database_errors_reveal_nothing(
    terminal: FakeTerminal, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    from faststudio.contrib.auth import DatabaseAuthBackend  # noqa: PLC0415

    async def broken(self: object, session: object, username: str) -> None:
        raise IntegrityError("SELECT secret FROM t", {"p": "hidden"}, Exception("orig detail"))

    monkeypatch.setattr(DatabaseAuthBackend, "find_account", broken)
    assert cli(terminal, "changepassword", "x", "--app", f"{APP}:contrib") == 1
    assert terminal.err == ["Database error (IntegrityError). Nothing was changed."]


def test_too_many_codenames_warn(
    terminal: FakeTerminal, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from faststudio.cli import _commands  # noqa: PLC0415

    monkeypatch.setattr(_commands, "MAX_CODENAMES", 3)
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib", "--dry-run") == 0
    assert "exceed 3" in terminal.text


def test_sync_without_a_name_field(db: str) -> None:
    """A schema without name_field (e.g. a custom backend) still syncs codenames."""
    from fastapi import FastAPI  # noqa: PLC0415

    from faststudio import Admin, ModelAdmin  # noqa: PLC0415
    from faststudio.api._permission_sync import apply_sync, plan_sync  # noqa: PLC0415
    from tests.factories.auth_models import (  # noqa: PLC0415
        AuthBase,
        AuthPermission,
        Folder,
        PermBackend,
    )

    class FolderAdmin(ModelAdmin, model=Folder):
        identity = "folders"

    async def run() -> set[str]:
        engine = create_async_engine(db)
        async with engine.begin() as conn:
            await conn.run_sync(AuthBase.metadata.create_all)
        admin = Admin(FastAPI(), engine=engine, auth_backend=PermBackend(), secret_key=apps.SECRET)
        admin.register(FolderAdmin)
        rules = admin._escalation
        assert rules is not None
        assert rules.name_column is None
        async with admin._session_maker() as session, session.begin():
            plan = await plan_sync(session, rules, admin._registry)
            assert plan.renamed == []
            await apply_sync(session, rules, plan, prune=True)
        async with AsyncSession(engine) as session:
            stored = set(await session.scalars(select(AuthPermission.codename)))
        async with engine.begin() as conn:
            await conn.run_sync(AuthBase.metadata.drop_all)
        await engine.dispose()
        return stored

    assert _run(run()) == {"folders.view", "folders.create", "folders.edit", "folders.delete"}


def test_checkusers_fix_skips_vanished_rows(db: str) -> None:
    from faststudio.contrib.auth import DatabaseAuthBackend  # noqa: PLC0415

    async def run() -> None:
        engine = create_async_engine(db)
        async with AsyncSession(engine) as session:
            await DatabaseAuthBackend(AUTH).fix(session, ["404", "x"])
        await engine.dispose()

    _run(run())


# --------------------------------------------------------------------------- review follow-ups


def test_load_errors_are_short_messages(
    terminal: FakeTerminal, url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FASTSTUDIO_SECRET_KEY", raising=False)
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:env_secret") == 2
    assert "Cannot load" in terminal.text
    assert "FASTSTUDIO_SECRET_KEY" in terminal.text
    terminal.err.clear()
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:broken") == 2
    # The factory failed when called, not at import: the type only, no message.
    assert terminal.err == [f"Calling {APP}:broken() failed (RuntimeError)."]
    assert "hunter2" not in terminal.text
    (tmp_path / "cli_boom_mod.py").write_text("raise ValueError('at import')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    terminal.err.clear()
    assert cli(terminal, "syncpermissions", "--app", "cli_boom_mod:admin") == 2
    assert "(ValueError)" in terminal.text
    (tmp_path / "cli_config_mod.py").write_text(
        "from faststudio import ConfigurationError\nraise ConfigurationError('bad option')\n",
        encoding="utf-8",
    )
    terminal.err.clear()
    assert cli(terminal, "syncpermissions", "--app", "cli_config_mod:admin") == 2
    assert terminal.err == ["Cannot load cli_config_mod:admin: bad option"]


@pytest.mark.parametrize(
    ("stop", "code", "message"),
    [(EOFError, 1, "Aborted"), (KeyboardInterrupt, 130, "Interrupted")],
)
def test_ctrl_d_and_ctrl_c_at_prompts(
    db: str, stop: type[BaseException], code: int, message: str
) -> None:
    from faststudio.cli import CliIO  # noqa: PLC0415

    def interrupted(prompt: str) -> str:
        raise stop

    out: list[str] = []
    io = CliIO(
        read_line=interrupted,
        read_password=interrupted,
        is_tty=lambda: True,
        write=out.append,
        error=out.append,
    )
    assert main(["createadmin", "--app", f"{APP}:contrib"], io=io) == code
    assert any(message in line for line in out)
    assert _run(_query(db, select(AUTH.user))) == []


def test_engines_routed_by_binds_are_used_and_disposed(terminal: FakeTerminal, db: str) -> None:
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:binds_only") == 0, terminal.text
    assert len(_codenames(db)) == 12  # users, groups, permissions


def test_other_databases_use_a_savepoint_per_insert(
    terminal: FakeTerminal, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import insert as plain_insert  # noqa: PLC0415

    from faststudio.api import _permission_sync  # noqa: PLC0415
    from faststudio.api._permission_sync import apply_sync, plan_sync  # noqa: PLC0415
    from faststudio.cli._app import load_admin  # noqa: PLC0415

    monkeypatch.setattr(_permission_sync, "_UPSERT_DIALECTS", frozenset())
    monkeypatch.setattr(
        _permission_sync,
        "_insert_ignoring_duplicates",
        lambda table, column, dialect: plain_insert(table),
    )

    async def both() -> None:
        admin = load_admin(f"{APP}:contrib")
        rules, registry, maker = admin._escalation, admin._registry, admin._session_maker
        assert rules is not None
        async with maker() as first, maker() as second:
            plan_a = await plan_sync(first, rules, registry)
            plan_b = await plan_sync(second, rules, registry)
            await apply_sync(first, rules, plan_a, prune=False)
            await first.commit()
            await apply_sync(second, rules, plan_b, prune=False)  # every insert collides
            await second.commit()
        await maker.kw["bind"].dispose()

    _run(both())
    assert len(_codenames(db)) == 17


def test_insert_statements_per_dialect() -> None:
    from sqlalchemy.dialects import mysql  # noqa: PLC0415

    from faststudio.api._permission_sync import _insert_ignoring_duplicates  # noqa: PLC0415

    table = AUTH.permission.__table__  # type: ignore[attr-defined]
    statement = _insert_ignoring_duplicates(table, table.c.codename, "mysql")
    sql = str(statement.compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "IGNORE" not in sql  # data errors (truncation) must still raise
    from sqlalchemy import Column, Integer, MetaData, String, Table  # noqa: PLC0415

    keyed = Table(
        "keyed_perms",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("code_name", String(100), key="codename", unique=True),
    )
    renamed = _insert_ignoring_duplicates(keyed, keyed.c.codename, "mysql")
    # A no-op update: never re-key a row matched through another unique index.
    rendered = str(renamed.compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE code_name = keyed_perms.code_name" in rendered
    assert "VALUES(" not in rendered.split("ON DUPLICATE KEY UPDATE", 1)[1]
    plain = _insert_ignoring_duplicates(table, table.c.codename, "oracle")
    assert "IGNORE" not in str(plain)


def test_the_created_check_reads_the_latest_rows_on_mysql(url: str) -> None:
    """Under REPEATABLE READ a plain SELECT could miss a concurrent worker's codename."""
    from sqlalchemy.dialects import mysql  # noqa: PLC0415

    from faststudio.api._permission_sync import _created_query  # noqa: PLC0415
    from faststudio.cli._app import load_admin  # noqa: PLC0415

    rules = load_admin(f"{APP}:contrib")._escalation
    assert rules is not None
    del url  # the admin's engine needs a URL; nothing is queried
    on_mysql = _created_query(rules, ["a.view"], "mysql").compile(dialect=mysql.dialect())
    assert str(on_mysql).endswith("LOCK IN SHARE MODE")
    elsewhere = _created_query(rules, ["a.view"], "postgresql")  # a plain read
    assert "LOCK IN SHARE MODE" not in str(elsewhere.compile(dialect=mysql.dialect()))


def test_permissions_that_cannot_be_created_fail_the_sync(
    terminal: FakeTerminal, db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MySQL skips a row colliding on another unique column: the sync must notice."""
    from sqlalchemy import text  # noqa: PLC0415

    from faststudio.api import _permission_sync  # noqa: PLC0415

    class Swallowed:  # what MySQL's no-op upsert does for such a row: nothing
        def values(self, _values: object) -> object:
            return text("SELECT 1")

    monkeypatch.setattr(_permission_sync, "_insert_ignoring_duplicates", lambda *_args: Swallowed())
    assert cli(terminal, "syncpermissions", "--app", f"{APP}:contrib") == 1
    assert "could not be created" in terminal.text
    assert "another unique column" in terminal.text
    assert "Nothing was changed." in terminal.text
    assert not _codenames(db)  # rolled back
