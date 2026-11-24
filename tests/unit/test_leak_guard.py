"""The test suite's guard against leaked aiosqlite connections (tests/_leaks.py)."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from tests._leaks import aiosqlite_workers, assert_no_leaked_workers, check_identifiable


def test_an_open_connection_is_reported_and_a_closed_one_is_not() -> None:
    before = aiosqlite_workers()
    loop = asyncio.new_event_loop()
    connection = loop.run_until_complete(aiosqlite.connect(":memory:"))
    try:
        with pytest.raises(pytest.fail.Exception, match="left 1 aiosqlite connection"):
            assert_no_leaked_workers(before, timeout=0.1)
    finally:
        loop.run_until_complete(connection.close())
        loop.close()
    assert_no_leaked_workers(before, timeout=2)  # closed: its worker thread exits


def test_workers_are_identifiable() -> None:
    check_identifiable()  # also runs once per session from tests/conftest.py


def test_unidentifiable_workers_fail_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tests._leaks.WORKER_TARGET", "renamed_in_a_new_aiosqlite")
    with pytest.raises(pytest.fail.Exception, match="cannot identify aiosqlite worker threads"):
        check_identifiable()
