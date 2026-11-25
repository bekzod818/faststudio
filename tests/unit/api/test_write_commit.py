"""Database errors during a write never leak SQL or values (threat model T5)."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from faststudio.api.errors import ApiError
from faststudio.api.write import _writing
from faststudio.auth.guard import WriteRefused


class _FailingSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.rolled_back = False
        self.committed = False

    async def commit(self) -> None:
        if self.error is not None:
            raise self.error
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _Registered:
    identity = "notes"


def _error(cls: type[Any], orig: Exception | None = None) -> Exception:
    error: Exception = cls("UPDATE notes SET title=?", ("SECRET-VALUE",), orig or Exception("boom"))
    return error


def _busy() -> sqlite3.OperationalError:
    orig = sqlite3.OperationalError("database is locked")
    orig.sqlite_errorcode = 5
    return orig


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (_error(IntegrityError), 409, "conflict"),
        (_error(DataError), 422, "validation_error"),
        (_error(OperationalError), 500, "internal_error"),
        (_error(OperationalError, _busy()), 409, "conflict"),  # lost a lock race
    ],
)
async def test_write_maps_database_errors(
    error: Exception, status: int, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    session = _FailingSession(error)
    with caplog.at_level("INFO", logger="faststudio"), pytest.raises(ApiError) as exc_info:
        async with _writing(session, _Registered(), "update"):  # type: ignore[arg-type]  # duck-typed fakes
            pass  # the commit fails
    assert (exc_info.value.status_code, exc_info.value.code) == (status, code)
    assert session.rolled_back
    assert "SECRET-VALUE" not in caplog.text
    assert "UPDATE notes" not in caplog.text
    assert "locked" not in exc_info.value.message
    assert type(error).__name__ in caplog.text


async def test_guard_refusal_rolls_back_with_its_code() -> None:
    session = _FailingSession()
    with pytest.raises(ApiError) as exc_info:
        async with _writing(session, _Registered(), "delete"):  # type: ignore[arg-type]  # duck-typed fakes
            raise WriteRefused("self_lockout", "You cannot delete your own account.")
    error = exc_info.value
    assert (error.status_code, error.code, error.message) == (
        409,
        "self_lockout",
        "You cannot delete your own account.",
    )
    assert session.rolled_back
    assert not session.committed
