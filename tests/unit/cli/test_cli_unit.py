"""CLI pieces without a database (M19)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from faststudio.cli import CliIO, console_main
from faststudio.cli import _io as io_module
from faststudio.cli._app import load_admin
from faststudio.cli._io import CliError


def test_default_terminal(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = CliIO()
    terminal.write("out")
    terminal.error("err")
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("out\n", "err\n")

    class FakeStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", FakeStdin())
    assert terminal.is_tty() is False  # looked up at call time
    with pytest.raises(CliError) as refused:
        terminal.need_terminal("Reading a password")
    assert refused.value.code == 2
    assert io_module._stdin_is_tty() is False


def test_console_main_exits_with_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["faststudio"])
    with pytest.raises(SystemExit) as exited:
        console_main()
    assert exited.value.code == 2


def test_app_modules_next_to_the_working_directory_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cli_probe_mod.py").write_text("thing = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(tmp_path)])
    with pytest.raises(CliError, match=r"is not a faststudio\.Admin"):
        load_admin("cli_probe_mod:thing")
    assert sys.path[0] == str(tmp_path)
