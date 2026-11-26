"""Classify database errors raised by writes (private)."""

from __future__ import annotations

from sqlalchemy.exc import StatementError

# SQLite primary result codes: SQLITE_BUSY (incl. BUSY_SNAPSHOT/RECOVERY/TIMEOUT
# extended codes) and SQLITE_LOCKED. The low byte is the primary code.
_SQLITE_LOCK_CODES = frozenset({5, 6})
# PostgreSQL SQLSTATEs: serialization_failure, deadlock_detected, lock_not_available.
_SQLSTATE_LOCK_CODES = frozenset({"40001", "40P01", "55P03"})
# MySQL/MariaDB: ER_LOCK_WAIT_TIMEOUT, ER_LOCK_DEADLOCK.
_MYSQL_LOCK_CODES = frozenset({1205, 1213})


def is_lock_conflict(exc: StatementError) -> bool:
    """Return True if the write lost a race for a lock or a consistent snapshot.

    Such errors are expected under concurrent writes (another request changed
    or locked the same rows first); the API answers ``409 conflict`` instead of
    a server error. Only error codes are inspected, never driver messages
    (Python >= 3.11 always sets ``sqlite_errorcode`` on SQLite errors).
    """
    orig = exc.orig
    sqlite_code = getattr(orig, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int):
        return sqlite_code & 0xFF in _SQLITE_LOCK_CODES
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if isinstance(sqlstate, str):
        return sqlstate in _SQLSTATE_LOCK_CODES
    args: tuple[object, ...] = getattr(orig, "args", ())
    number = args[0] if args else None
    return type(number) is int and number in _MYSQL_LOCK_CODES


# Lost races that end at once (no lock wait): deadlock victims and serialization
# failures. Lock-wait timeouts (55P03, MySQL 1205, SQLite BUSY) are excluded:
# they already waited the configured time.
_SQLSTATE_RACES = frozenset({"40001", "40P01"})
_MYSQL_RACES = frozenset({1213})


def is_lost_race(exc: StatementError) -> bool:
    """Return True for a deadlock victim or a serialization failure (retry at once)."""
    orig = exc.orig
    if isinstance(getattr(orig, "sqlite_errorcode", None), int):
        return False  # SQLite waits for locks (busy timeout) instead of deadlocking
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if isinstance(sqlstate, str):
        return sqlstate in _SQLSTATE_RACES
    args: tuple[object, ...] = getattr(orig, "args", ())
    number = args[0] if args else None
    return type(number) is int and number in _MYSQL_RACES
