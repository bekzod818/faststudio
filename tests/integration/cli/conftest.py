from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from faststudio.cli import CliIO


@dataclass
class FakeTerminal:
    """Scripted input; captures output. Passwords come only from `passwords`."""

    lines: list[str] = field(default_factory=list)
    passwords: list[str] = field(default_factory=list)
    tty: bool = True
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)

    def io(self) -> CliIO:
        return CliIO(
            read_line=lambda prompt: self.lines.pop(0),
            read_password=lambda prompt: self.passwords.pop(0),
            is_tty=lambda: self.tty,
            write=self.out.append,
            error=self.err.append,
        )

    @property
    def text(self) -> str:
        return "\n".join([*self.out, *self.err])


@pytest.fixture
def terminal() -> FakeTerminal:
    return FakeTerminal()
