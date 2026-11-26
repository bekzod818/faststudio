"""Which database errors the startup sync retries at once (item 2)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from faststudio.api._db_errors import is_lock_conflict, is_lost_race


class _SqliteError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__("database is locked")
        self.sqlite_errorcode = code


class _PostgresError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("x")
        self.sqlstate = sqlstate


class _MysqlError(Exception):
    def __init__(self, number: int) -> None:
        super().__init__(number, "x")


def _wrapped(orig: Exception) -> OperationalError:
    return OperationalError("INSERT ...", {}, orig)


@pytest.mark.parametrize(
    ("orig", "lost_race", "lock_conflict"),
    [
        (_PostgresError("40P01"), True, True),  # deadlock_detected
        (_PostgresError("40001"), True, True),  # serialization_failure
        (_PostgresError("55P03"), False, True),  # lock_not_available: it already waited
        (_PostgresError("42P01"), False, False),  # undefined_table
        (_MysqlError(1213), True, True),  # ER_LOCK_DEADLOCK
        (_MysqlError(1205), False, True),  # ER_LOCK_WAIT_TIMEOUT
        (_MysqlError(1146), False, False),  # no such table
        (_SqliteError(5), False, True),  # SQLITE_BUSY after the busy timeout
        (Exception("no code"), False, False),
    ],
)
def test_only_races_that_ended_at_once_are_lost_races(
    orig: Exception,
    lost_race: bool,
    lock_conflict: bool,
) -> None:
    error = _wrapped(orig)
    assert is_lost_race(error) is lost_race
    assert is_lock_conflict(error) is lock_conflict
