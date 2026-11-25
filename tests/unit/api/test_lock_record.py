"""How many-to-many writes lock the record's row, per dialect (ADR-0010, M15 follow-up)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects.mysql.base import MySQLDialect
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.engine import Dialect

from faststudio import ModelAdmin
from faststudio.api.write import _lock_record
from faststudio.registry import resolve_model_admin
from tests.factories.models import Post


class _Bind:
    def __init__(self, dialect: Dialect) -> None:
        self.dialect = dialect


class _Session:
    """Records the statements `_lock_record` executes."""

    def __init__(self, dialect: Dialect) -> None:
        self.bind = _Bind(dialect)
        self.statements: list[Any] = []

    def get_bind(self, **_kwargs: Any) -> _Bind:
        return self.bind

    async def execute(self, statement: Any, **_kwargs: Any) -> None:
        self.statements.append(statement)


class _PostAdmin(ModelAdmin, model=Post):
    many_to_many = ("tags",)


# SQLAlchemy's dialect constructors are not annotated.
_DIALECTS: list[Dialect] = [PGDialect(), MySQLDialect()]  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("dialect", _DIALECTS)
async def test_select_for_update_never_writes_the_row(dialect: Dialect) -> None:
    session = _Session(dialect)
    await _lock_record(session, resolve_model_admin(_PostAdmin, max_page_size=100), 1)  # type: ignore[arg-type]  # duck-typed fake
    (statement,) = session.statements
    sql = str(statement.compile(dialect=dialect))
    assert sql.startswith("SELECT posts.id")
    assert "FOR UPDATE" in sql
    assert "UPDATE posts" not in sql.replace("FOR UPDATE", "")


async def test_sqlite_takes_its_write_lock_with_a_no_change_update() -> None:
    dialect = SQLiteDialect()
    session = _Session(dialect)
    await _lock_record(session, resolve_model_admin(_PostAdmin, max_page_size=100), 1)  # type: ignore[arg-type]  # duck-typed fake
    (statement,) = session.statements
    assert str(statement.compile(dialect=dialect)).startswith("UPDATE posts SET id=posts.id")
