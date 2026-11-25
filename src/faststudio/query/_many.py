"""Statements for many-to-many fields: read and write the association table (ADR-0010)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, TypeVar

from sqlalchemy import Delete, Insert, Select, Update, delete, insert, select, update

from faststudio.introspection._many import ManyToManyLink

_T = TypeVar("_T")

#: Most keys per statement. IN (...) lists bind one parameter per key, multi-row
#: inserts two, so both stay within SQLite's historical limit of 999 parameters.
CHUNK_SIZE = 500
INSERT_CHUNK_SIZE = CHUNK_SIZE // 2


def chunks(values: Sequence[_T], size: int = CHUNK_SIZE) -> Iterator[Sequence[_T]]:
    """Yield `values` in slices of at most `size` items."""
    for start in range(0, len(values), size):
        yield values[start : start + size]


def linked_keys_statement(link: ManyToManyLink, pk: object, limit: int) -> Select[Any]:
    """Distinct target keys linked to the row `pk`, in key order, at most `limit`."""
    return (
        select(link.remote_fk)
        .where(link.local_fk == pk)
        .distinct()
        .order_by(link.remote_fk)
        .limit(limit)
    )


def locked_keys_statement(link: ManyToManyLink, pk: object, limit: int) -> Select[Any]:
    """Target keys linked to `pk` with a locking read (`FOR SHARE`), at most `limit` rows.

    A locking read sees the latest committed rows also under MySQL's
    REPEATABLE READ. PostgreSQL forbids `FOR SHARE` with `DISTINCT`, so
    duplicates (only possible when other code writes a table without a unique
    pair) are removed by the caller.
    """
    return (
        select(link.remote_fk)
        .where(link.local_fk == pk)
        .order_by(link.remote_fk)
        .limit(limit)
        .with_for_update(read=True)
    )


def touch_record_statement(link: ManyToManyLink, pk: object) -> Update:
    """`UPDATE` the record's row without changing it: SQLite's write lock.

    Used only on SQLite, which has no `SELECT ... FOR UPDATE`. Setting the
    primary key (and every column with an `onupdate` default) to itself changes
    nothing, so SQLAlchemy `onupdate` columns are not bumped; SQLite `ON
    UPDATE` triggers on the table do fire.
    """
    table = link.local_pk.table
    unchanged = {link.local_pk.key: link.local_pk}
    unchanged.update(
        {column.key: column for column in table.columns if column.onupdate is not None}
    )
    return update(table).where(link.local_pk == pk).values(unchanged)


def existing_keys_statement(link: ManyToManyLink, keys: Sequence[object]) -> Select[Any]:
    """Which of `keys` exist as target primary keys (one chunk)."""
    return select(link.target_pk).where(link.target_pk.in_(list(keys)))


def insert_links_statement(link: ManyToManyLink, pk: object, keys: Sequence[object]) -> Insert:
    """Insert one association row per key for the row `pk`."""
    return insert(link.secondary).values(
        [{link.local_fk.key: pk, link.remote_fk.key: key} for key in keys]
    )


def delete_links_statement(
    link: ManyToManyLink, pk: object, keys: Sequence[object] | None = None
) -> Delete:
    """Delete the links of the row `pk` (only to `keys` when given)."""
    statement = delete(link.secondary).where(link.local_fk == pk)
    if keys is not None:
        statement = statement.where(link.remote_fk.in_(list(keys)))
    return statement


def delete_links_to_statement(link: ManyToManyLink, target_pk: object) -> Delete:
    """Delete every link pointing at the target row `target_pk` (it is being deleted)."""
    return delete(link.secondary).where(link.remote_fk == target_pk)
