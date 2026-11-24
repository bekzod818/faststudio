"""Database errors during commit never leak SQL or values (threat model T5)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from faststudio.api.errors import ApiError
from faststudio.api.write import _commit


class _FailingSession:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.rolled_back = False

    async def commit(self) -> None:
        raise self.error

    async def rollback(self) -> None:
        self.rolled_back = True


class _Registered:
    identity = "notes"


def _error(cls: type[Any]) -> Exception:
    error: Exception = cls("UPDATE notes SET title=?", ("SECRET-VALUE",), Exception("boom"))
    return error


@pytest.mark.parametrize(
    ("cls", "status", "code"),
    [
        (IntegrityError, 409, "conflict"),
        (DataError, 422, "validation_error"),
        (OperationalError, 500, "internal_error"),
    ],
)
async def test_commit_maps_database_errors(
    cls: type[Any], status: int, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    session = _FailingSession(_error(cls))
    with caplog.at_level("INFO", logger="faststudio"), pytest.raises(ApiError) as exc_info:
        await _commit(session, _Registered(), "update")  # type: ignore[arg-type]  # duck-typed fakes
    assert (exc_info.value.status_code, exc_info.value.code) == (status, code)
    assert session.rolled_back
    assert "SECRET-VALUE" not in caplog.text
    assert "UPDATE notes" not in caplog.text
    assert cls.__name__ in caplog.text
