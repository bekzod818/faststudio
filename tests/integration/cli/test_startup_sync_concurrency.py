"""N processes starting at once: startup sync never fails or logs (item 2, M19 follow-up).

Runs on SQLite, and on PostgreSQL / MySQL when FASTSTUDIO_TEST_POSTGRES_URL /
FASTSTUDIO_TEST_MYSQL_URL point at a throwaway ``*_test`` database.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from faststudio.api._startup_sync import RACE_ATTEMPTS
from tests._databases import MYSQL_URL, mysql_param
from tests.factories.contrib_models import AUTH, ContribBase

ROOT = Path(__file__).resolve().parents[3]
PROCESSES = int(os.environ.get("SYNC_PROCESSES", "8"))
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")


def _url(kind: str, tmp_path: Path) -> str:
    if kind == "sqlite":
        return f"sqlite+aiosqlite:///{tmp_path}/concurrent.db"
    url = POSTGRES_URL if kind == "postgres" else MYSQL_URL
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Refusing to drop tables: use a database named *_test.")
    return url


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.drop_all)
        await conn.run_sync(ContribBase.metadata.create_all)
    await engine.dispose()


async def _stored(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            return set(await session.scalars(select(AUTH.permission.codename)))
    finally:
        await engine.dispose()


async def _drop(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(ContribBase.metadata.drop_all)
    await engine.dispose()


def _wait_until_ready(barrier: Path, workers: list[subprocess.Popen[str]], deadline: float) -> None:
    """Every worker has imported and built its admin (ready file), or fail."""
    while len(list(barrier.glob("ready-*"))) < len(workers):
        if time.monotonic() > deadline:
            pytest.fail("the workers did not get ready in time")
        for worker in workers:
            if worker.poll() is not None:
                pytest.fail(f"a worker exited early: {worker.communicate()[1]}")
        time.sleep(0.05)


@pytest.mark.parametrize(
    "kind",
    [
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
            ],
        ),
        mysql_param("mysql"),
    ],
)
def test_many_processes_starting_at_once(kind: str, tmp_path: Path) -> None:
    url = _url(kind, tmp_path)
    asyncio.run(_reset(url))
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    deadline = time.monotonic() + 180  # one budget for the whole test
    env = {**os.environ, "FASTSTUDIO_SYNC_DATABASE_URL": url}
    workers = [
        subprocess.Popen(
            [sys.executable, "-m", "tests.integration.cli._sync_worker", str(barrier)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(PROCESSES)
    ]
    try:
        _wait_until_ready(barrier, workers, deadline)
        (barrier / "start").touch()
        results = [
            worker.communicate(timeout=max(1.0, deadline - time.monotonic())) for worker in workers
        ]
        stored = asyncio.run(_stored(url))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()  # reap, close the pipes
        try:
            asyncio.run(_drop(url))
        except Exception as exc:
            warnings.warn(f"could not drop the test tables: {exc!r}", stacklevel=1)
    racing = 0
    for worker, (out, err) in zip(workers, results, strict=True):
        assert worker.returncode == 0, err
        assert "Traceback" not in err, err
        report = json.loads(out.strip().splitlines()[-1])
        assert report["status"] == 401  # anonymous /auth/me
        assert report["logs"] == []  # nothing logged at WARNING or above
        assert 1 <= len(report["missing"]) <= RACE_ATTEMPTS  # a lost race may retry
        assert stored == set(report["expected"])  # every permission, nothing else
        racing += report["missing"][0] > 0
    assert racing >= 2  # the processes really raced to insert the same codenames
