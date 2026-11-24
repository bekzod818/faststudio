"""Wheel smoke tests use the SPA bundled in the installed wheel."""

import pytest


@pytest.fixture(autouse=True)
def _no_built_spa() -> None:
    """Override the suite-wide fixture: here the wheel's own static files are the point."""
