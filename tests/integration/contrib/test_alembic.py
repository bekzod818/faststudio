"""Alembic autogenerate sees the contrib.auth tables, and nothing after create_all."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests._databases import MYSQL_URL, mysql_param, throwaway
from tests.factories.contrib_models import ContribBase

POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
AUTH_TABLES = {
    "faststudio_user",
    "faststudio_group",
    "faststudio_permission",
    "faststudio_user_groups",
    "faststudio_user_permissions",
    "faststudio_group_permissions",
}


def _auth_metadata() -> MetaData:
    metadata = MetaData()
    for name in sorted(AUTH_TABLES):
        ContribBase.metadata.tables[name].to_metadata(metadata)
    return metadata


def _ours(name: str | None, type_: str, parent_names: Any) -> bool:
    """Compare only the contrib tables (the database may hold others)."""
    del parent_names
    return type_ != "table" or name in AUTH_TABLES


def _diff(connection: Any, metadata: MetaData) -> list[Any]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "include_name": _ours}
    )
    return list(compare_metadata(context, metadata))


@pytest.mark.parametrize(
    "url",
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
async def test_autogenerate_round_trip(url: str, tmp_path: Path) -> None:
    if url == "postgres":
        assert (make_url(POSTGRES_URL).database or "").endswith("_test")
        engine = create_async_engine(POSTGRES_URL)
    elif url == "mysql":
        engine = create_async_engine(throwaway(MYSQL_URL))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/alembic.db")
    metadata = _auth_metadata()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.drop_all)
            added = await conn.run_sync(_diff, metadata)
            new_tables = {op[1].name for op in added if op[0] == "add_table"}
            assert new_tables == AUTH_TABLES
            await conn.run_sync(metadata.create_all)
            assert await conn.run_sync(_diff, metadata) == []  # nothing left to migrate
            await conn.run_sync(metadata.drop_all)
    finally:
        await engine.dispose()
