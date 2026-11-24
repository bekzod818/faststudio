"""Detect aiosqlite connections a test leaves open (v0.1.1, A2).

An open aiosqlite connection keeps a worker thread alive. If its event loop
closes first, the thread later fails with "Event loop is closed", and pytest
reports that (``filterwarnings = error``) in whichever test happens to run
next. The autouse fixture in tests/conftest.py joins new worker threads at
the end of each test, so a leak fails the test that caused it.

The threads are recognised by their target's name, a private detail of
aiosqlite. ``check_identifiable()`` runs once per session and fails loudly if
that stops working, instead of letting the guard pass silently. aiosqlite is
pinned to 0.22.x in the dev group and the test-lowest CI job for the same reason.

TODO(omnilib/aiosqlite#397): when a release awaits the worker shutdown after a
failed connect, drop the workaround in
tests/integration/test_example_app.py (corrupt file instead of a missing
directory) and revisit the pin.
"""

from __future__ import annotations

import asyncio
import threading

import aiosqlite
import pytest

#: Thread target of aiosqlite's per-connection worker (`aiosqlite.core`). Python >= 3.10
#: appends the target's name to default thread names: `Thread-N (_connection_worker_thread)`
#: (aiosqlite 0.22+; 0.21 used a different target).
WORKER_TARGET = "_connection_worker_thread"


def aiosqlite_workers() -> set[threading.Thread]:
    """Return the live aiosqlite worker threads."""
    return {t for t in threading.enumerate() if t.is_alive() and WORKER_TARGET in t.name}


def assert_no_leaked_workers(before: set[threading.Thread], *, timeout: float = 2.0) -> None:
    """Fail if worker threads started since `before` are still alive after `timeout`.

    Joining also lets a closing connection's thread finish now, so any error it
    raises is attributed to the current test.
    """
    leaked = []
    for thread in aiosqlite_workers() - before:
        thread.join(timeout)
        if thread.is_alive():
            leaked.append(thread.name)
    if leaked:
        pytest.fail(
            f"Test left {len(leaked)} aiosqlite connection(s) open: dispose the engine "
            f"(`await engine.dispose()`) or close the connection. Threads: {sorted(leaked)}",
            pytrace=False,
        )


def check_identifiable() -> None:
    """Fail loudly if aiosqlite worker threads can no longer be recognised."""

    async def open_and_look() -> bool:
        async with aiosqlite.connect(":memory:") as connection:
            await connection.execute("SELECT 1")
            return bool(aiosqlite_workers())

    if not asyncio.run(open_and_look()):
        pytest.fail(
            f"The leak guard cannot identify aiosqlite worker threads (no live thread "
            f"named after {WORKER_TARGET!r} while a connection is open). aiosqlite's "
            "internals changed: update tests/_leaks.py.",
            pytrace=False,
        )
