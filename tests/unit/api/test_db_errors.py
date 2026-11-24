"""Lock-race database errors are recognised across drivers."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from faststudio.api._db_errors import is_lock_conflict


class _PgError(Exception):
    def __init__(self, sqlstate: str, *, attribute: str = "sqlstate") -> None:
        super().__init__("driver message")
        setattr(self, attribute, sqlstate)


def _wrap(orig: BaseException) -> StatementError:
    return OperationalError("UPDATE t SET x = ?", {}, orig)


def _sqlite(code: int, message: str = "database is locked") -> sqlite3.OperationalError:
    error = sqlite3.OperationalError(message)
    error.sqlite_errorcode = code
    return error


@pytest.mark.parametrize(
    ("orig", "expected"),
    [
        (_sqlite(5), True),  # SQLITE_BUSY
        (_sqlite(517), True),  # SQLITE_BUSY_SNAPSHOT
        (_sqlite(6, "database table is locked"), True),  # SQLITE_LOCKED
        (_sqlite(1, "no such table: t"), False),  # SQLITE_ERROR
        (_sqlite(19, "UNIQUE constraint failed"), False),  # SQLITE_CONSTRAINT
        (_PgError("40001"), True),  # serialization_failure (REPEATABLE READ / SERIALIZABLE)
        (_PgError("40P01"), True),  # deadlock_detected
        (_PgError("55P03", attribute="pgcode"), True),  # lock_not_available
        (_PgError("23505"), False),  # unique_violation
        (Exception(1213, "Deadlock found"), True),  # MySQL ER_LOCK_DEADLOCK
        (Exception(1205, "Lock wait timeout"), True),  # MySQL ER_LOCK_WAIT_TIMEOUT
        (Exception(1062, "Duplicate entry"), False),
        (Exception(True), False),  # a bool is not an error number
        (Exception("database is locked"), False),  # messages are never inspected
        (Exception("disk I/O error"), False),
    ],
)
def test_lock_conflicts(orig: BaseException, expected: bool) -> None:
    assert is_lock_conflict(_wrap(orig)) is expected


def test_integrity_errors_are_not_lock_conflicts() -> None:
    error = IntegrityError("INSERT", {}, _sqlite(2067, "UNIQUE constraint failed: t.x"))
    assert is_lock_conflict(error) is False
