"""The shipped package has no test-only hooks (M20; threat model T1).

Tests control session time only by passing ``clock=`` to `SessionManager`
from test code (pytest fixtures, the Playwright launcher tests/e2e/idle_server.py).
The package itself must never read an environment variable or flag that
shifts time or bypasses a check, nor offer a route for it. This test scans
whatever `faststudio` is imported, so the wheel smoke job checks the
installed wheel too.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

import faststudio
from faststudio.auth.session import SessionManager

PACKAGE = Path(faststudio.__file__).resolve().parent
SOURCES = sorted(PACKAGE.rglob("*.py"))
#: The only module that may read the environment, and the only name it reads.
ENV_READERS = {"security/secret.py": {"FASTSTUDIO_SECRET_KEY"}}


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


_ENV_NAMES = frozenset({"environ", "environb", "getenv", "getenvb", "putenv", "argv"})


def _env_access(tree: ast.AST) -> list[int]:
    """Line numbers of environment or argv access, however spelled.

    Attribute access (`os.environ`, `os.getenvb`, `sys.argv`), imports of
    those names, and `getattr(..., "environ")`-style string lookups.
    """
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _ENV_NAMES:
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in {"os", "sys"}:
            if {alias.name for alias in node.names} & _ENV_NAMES:
                lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value in _ENV_NAMES:
            lines.append(node.lineno)
    return lines


def _clock_writes(tree: ast.AST) -> list[int]:
    """Writes of a `_clock` attribute other than `self._clock = clock` (the parameter)."""
    lines = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets, value = [node.target], node.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
        ) or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__setattr__"
        ):
            if any(isinstance(a, ast.Constant) and a.value == "_clock" for a in node.args):
                lines.append(node.lineno)
            continue
        if any(isinstance(t, ast.Attribute) and t.attr == "_clock" for t in targets):
            from_parameter = isinstance(value, ast.Name) and value.id == "clock"
            if not from_parameter or isinstance(node, ast.AugAssign):
                lines.append(targets[0].lineno)
    return lines


def test_the_sources_are_scanned() -> None:
    assert len(SOURCES) > 50
    assert (PACKAGE / "auth" / "session.py") in SOURCES


def test_only_the_secret_key_is_read_from_the_environment() -> None:
    offenders = {}
    for path in SOURCES:
        lines = _env_access(ast.parse(path.read_text(encoding="utf-8")))
        if lines and _relative(path) not in ENV_READERS:
            offenders[_relative(path)] = lines
    assert offenders == {}
    secret = (PACKAGE / "security" / "secret.py").read_text(encoding="utf-8")
    assert 'SECRET_ENV_VAR = "FASTSTUDIO_SECRET_KEY"' in secret.replace("'", '"')


def test_sessions_always_use_the_real_clock() -> None:
    """No package code passes `clock=`; constructors only store their own parameter."""
    offenders = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(k.arg == "clock" for k in node.keywords):
                offenders.append(f"{_relative(path)}:{node.lineno}")
        offenders.extend(f"{_relative(path)}:{line}" for line in _clock_writes(tree))
    assert offenders == []
    assert SessionManager("k" * 48, max_age=60)._clock is time.time


def _paths(routes: list[Any]) -> set[str]:
    """Every route path, through routers FastAPI keeps nested."""
    found: set[str] = set()
    for route in routes:
        nested = getattr(route, "original_router", None)
        found |= _paths(list(nested.routes)) if nested is not None else {route.path}
    return found


def test_no_route_sets_time_or_bypasses_checks(
    app: FastAPI, engine: AsyncEngine, secret_key: str, auth_backend: faststudio.AuthBackend
) -> None:
    admin = faststudio.Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)
    paths = sorted(_paths(admin._sub_app.routes))
    assert paths == [
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/password",
        "/api/v1/auth/sign-out-everywhere",
        "/api/v1/meta",
        "/api/v1/models/{identity}/fields/{field}/choices",
        "/api/v1/models/{identity}/items",
        "/api/v1/models/{identity}/items/{pk}",
        "/api/v1/models/{identity}/items/{pk}/links",
        "/api/v1/models/{identity}/items/{pk}/password",
        "/assets",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "import os\nx = os.environb",
        "import os\nx = os.getenvb(b'X')",
        "import os\nx = getattr(os, 'environ')",
        "from os import environ",
        "import sys\nx = sys.argv",
    ],
)
def test_the_environment_scan_catches(source: str) -> None:
    assert _env_access(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "m._clock = lambda: 0",
        "m._clock: object = fake",
        "m._clock += 5",
        "setattr(m, '_clock', fake)",
        "object.__setattr__(m, '_clock', fake)",
    ],
)
def test_the_clock_scan_catches(source: str) -> None:
    assert _clock_writes(ast.parse(source))


def test_the_clock_scan_allows_the_constructor() -> None:
    assert _clock_writes(ast.parse("self._clock = clock")) == []
