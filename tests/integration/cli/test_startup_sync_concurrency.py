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
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.factories.contrib_models import AUTH, ContribBase

ROOT = Path(__file__).resolve().parents[3]
PROCESSES = int(os.environ.get("SYNC_PROCESSES", "8"))
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
MYSQL_URL = os.environ.get("FASTSTUDIO_TEST_MYSQL_URL", "")


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


async def _stored(url: str) -> tuple[int, int]:
    engine = create_async_engine(url)
    async with AsyncSession(engine) as session:
        rows = await session.scalar(select(func.count()).select_from(AUTH.permission))
        distinct = await session.scalar(select(func.count(AUTH.permission.codename.distinct())))
    await engine.dispose()
    return int(rows or 0), int(distinct or 0)


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
        pytest.param(
            "mysql",
            marks=[
                pytest.mark.mysql,
                pytest.mark.skipif(not MYSQL_URL, reason="set FASTSTUDIO_TEST_MYSQL_URL"),
            ],
        ),
    ],
)
def test_many_processes_starting_at_once(kind: str, tmp_path: Path) -> None:
    url = _url(kind, tmp_path)
    asyncio.run(_reset(url))
    start = tmp_path / "start"
    workers = [
        subprocess.Popen(
            [sys.executable, "-m", "tests.integration.cli._sync_worker", url, str(start)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(PROCESSES)
    ]
    try:
        # Every worker has imported and built its admin before any starts.
        import time  # noqa: PLC0415

        time.sleep(3)
        start.touch()
        results = [worker.communicate(timeout=120) for worker in workers]
    finally:
        for worker in workers:
            worker.kill()
    racing = 0
    for worker, (out, err) in zip(workers, results, strict=True):
        assert worker.returncode == 0, err
        assert "Traceback" not in err, err
        report = json.loads(out.strip().splitlines()[-1])
        assert report["status"] == 401  # anonymous /auth/me
        assert report["logs"] == []  # nothing logged at WARNING or above
        assert len(report["missing"]) == 1  # synced once, on the first attempt
        racing += report["missing"][0] > 0
    assert racing >= 2  # the processes really raced to insert the same codenames
    rows, distinct = asyncio.run(_stored(url))
    assert rows == distinct  # each codename exactly once
    assert rows >= 10  # notes.*, notes.publish, users/groups/permissions
