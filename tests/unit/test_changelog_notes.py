import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changelog_notes.py"

SAMPLE = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-12-01
### Added
- Two

## [0.1.0] - 2026-11-30
### Added
- One
"""


@pytest.fixture(scope="module")
def notes() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog_notes", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extracts_middle_section(notes: ModuleType) -> None:
    assert notes.extract(SAMPLE, "0.2.0") == "### Added\n- Two\n"


def test_extracts_last_section(notes: ModuleType) -> None:
    assert notes.extract(SAMPLE, "0.1.0") == "### Added\n- One\n"


def test_unknown_version(notes: ModuleType) -> None:
    with pytest.raises(LookupError):
        notes.extract(SAMPLE, "9.9.9")


def test_cli_usage(notes: ModuleType) -> None:
    assert notes.main([]) == 2
    assert notes.main(["9.9.9"]) == 1
