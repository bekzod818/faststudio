"""Server databases for the integration tests (PostgreSQL and MySQL; not a test module).

Tests run on SQLite always, and on a server when its URL points at a
throwaway database whose name ends in ``_test`` (tables there are dropped):

- ``FASTSTUDIO_TEST_POSTGRES_URL``, e.g. ``postgresql+asyncpg://u:p@localhost/faststudio_test``
- ``FASTSTUDIO_TEST_MYSQL_URL``, e.g. ``mysql+aiomysql://u:p@localhost/faststudio_test``
  (MySQL 8.4; the driver is ``aiomysql[rsa]``, see CONTRIBUTING.md)

The CI jobs select them with ``-m postgres`` / ``-m mysql`` and fail on skips.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.engine import make_url

POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")
MYSQL_URL = os.environ.get("FASTSTUDIO_TEST_MYSQL_URL", "")


def postgres_param(value: str) -> Any:
    """A fixture parameter that needs PostgreSQL."""
    return pytest.param(
        value,
        marks=[
            pytest.mark.postgres,
            pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
        ],
    )


def mysql_param(value: str) -> Any:
    """A fixture parameter that needs MySQL."""
    return pytest.param(
        value,
        marks=[
            pytest.mark.mysql,
            pytest.mark.skipif(not MYSQL_URL, reason="set FASTSTUDIO_TEST_MYSQL_URL"),
        ],
    )


def throwaway(url: str) -> str:
    """Return `url` if its database is a ``*_test`` one, else fail the test."""
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
    return url
