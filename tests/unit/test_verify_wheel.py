import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_wheel.py"


@pytest.fixture(scope="module")
def verify_wheel() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_wheel", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_wheel(tmp_path: Path, names: list[str]) -> Path:
    wheel = tmp_path / "faststudio-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        for name in names:
            zf.writestr(name, "x")
    return wheel


def test_valid_wheel(tmp_path: Path, verify_wheel: ModuleType) -> None:
    wheel = _make_wheel(
        tmp_path,
        ["faststudio/py.typed", "faststudio/static/index.html", "faststudio/static/assets/a.js"],
    )
    assert verify_wheel.verify(wheel) == []
    assert verify_wheel.main([str(wheel)]) == 0


def test_wheel_without_spa_fails(tmp_path: Path, verify_wheel: ModuleType) -> None:
    wheel = _make_wheel(tmp_path, ["faststudio/py.typed", "faststudio/static/assets/a.js.map"])
    problems = verify_wheel.verify(wheel)
    assert "missing faststudio/static/index.html" in problems
    assert any("JavaScript bundle" in p for p in problems)
    assert any("source maps" in p for p in problems)
    assert verify_wheel.main([str(wheel)]) == 1


def test_usage(verify_wheel: ModuleType) -> None:
    assert verify_wheel.main([]) == 2
