"""Smoke tests that run against an *installed* wheel in a clean virtualenv.

CI sets FASTSTUDIO_WHEEL_SMOKE=1 after `pip install dist/*.whl`. Locally these
tests are skipped because the import would resolve to the source tree.
"""

import os
from importlib import resources
from pathlib import Path

import pytest

import faststudio

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FASTSTUDIO_WHEEL_SMOKE") != "1",
        reason="set FASTSTUDIO_WHEEL_SMOKE=1 to run against an installed wheel",
    ),
]


def test_imports_from_site_packages() -> None:
    assert "site-packages" in Path(faststudio.__file__).parts


def test_spa_is_bundled() -> None:
    static = resources.files("faststudio") / "static"
    assert (static / "index.html").is_file()
    assert any(p.name.endswith(".js") for p in (static / "assets").iterdir())


def test_typed_marker_is_bundled() -> None:
    assert (resources.files("faststudio") / "py.typed").is_file()
