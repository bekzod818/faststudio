import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_commit_msg.py"


@pytest.fixture(scope="module")
def hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_commit_msg", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "subject",
    ["feat: add admin", "fix(auth): reject expired cookies", "feat(api)!: rename route", "Merge x"],
)
def test_valid(hook: ModuleType, subject: str) -> None:
    assert hook.is_valid(subject)


@pytest.mark.parametrize(
    "subject", ["Add admin", "feat:missing space", "feature: x", "fix(): x", ""]
)
def test_invalid(hook: ModuleType, subject: str) -> None:
    assert not hook.is_valid(subject)


def test_main(hook: ModuleType, tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.write_text("docs: update readme\n\nbody\n")
    bad = tmp_path / "bad"
    bad.write_text("updated\n")
    assert hook.main([str(good)]) == 0
    assert hook.main([str(bad)]) == 1
