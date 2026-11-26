"""One process of the concurrent startup-sync test (not a test module).

    python -m tests.integration.cli._sync_worker DATABASE_URL START_FILE

Builds the contrib admin with ``sync_permissions_on_startup=True``, waits
until START_FILE exists (so every process starts its first request at the
same moment), sends one request and prints the `faststudio` log records at
WARNING or above as JSON. Exit code 0 unless the request itself failed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

import faststudio.api._startup_sync as startup_sync
from faststudio import Admin
from faststudio.contrib.auth import DatabaseAuthBackend
from tests.factories.contrib_models import AUTH
from tests.integration.cli.apps import SECRET, NoteAdmin


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}")


async def _main(url: str, start: Path) -> int:
    seen: list[int] = []  # how many codenames this process found missing
    plan_sync = vars(startup_sync)["plan_sync"]

    async def recording_plan(*args: object, **kwargs: object) -> object:
        plan = await plan_sync(*args, **kwargs)
        seen.append(len(plan.missing))
        return plan

    vars(startup_sync)["plan_sync"] = recording_plan
    collect = _Collect()
    logging.getLogger("faststudio").addHandler(collect)
    engine = create_async_engine(url)
    app = FastAPI()
    admin = Admin(
        app,
        engine=engine,
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=SECRET,
        sync_permissions_on_startup=True,
    )
    admin.register(NoteAdmin)
    deadline = time.monotonic() + 60
    while not await asyncio.to_thread(start.exists):
        if time.monotonic() > deadline:
            return 3
        await asyncio.sleep(0.005)
    transport = httpx.ASGITransport(app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://t") as http:
            response = await http.get("/admin/api/v1/auth/me")
    finally:
        await engine.dispose()
    report = {"status": response.status_code, "logs": collect.records, "missing": seen}
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1], Path(sys.argv[2]))))
