"""Authorization costs nothing without a permission backend (ADR-0011 §3, M17)."""

from __future__ import annotations

import httpx
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_model_user_backend_adds_no_queries(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    """v0.1 behaviour: every admin holds ALL, resolved without a query."""
    statements: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *args: object) -> None:
        del args
        statements.append(statement)

    event.listen(db.sync_engine, "before_cursor_execute", record)
    try:
        assert (await api.get("/admin/api/v1/models/teams/items")).status_code == 200
        assert len(statements) == 3  # get_user, page, count
        statements.clear()
        assert (await api.get("/admin/api/v1/meta")).status_code == 200
        assert len(statements) == 1  # get_user; hooks of every model cost nothing
    finally:
        event.remove(db.sync_engine, "before_cursor_execute", record)
