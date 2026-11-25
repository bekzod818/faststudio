"""Terminal input and output for the CLI (injectable in tests)."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass


class CliError(Exception):
    """A refusal or usage error: the message is shown, `code` is the exit code."""

    def __init__(self, message: str, code: int = 1) -> None:
        """Create the error with a user-facing message (never a secret)."""
        super().__init__(message)
        self.code = code


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()  # looked up at call time (stdin may be replaced)


def _write(text: str) -> None:
    print(text)


def _error(text: str) -> None:
    print(text, file=sys.stderr)


@dataclass(slots=True)
class CliIO:
    """How the CLI talks to the user. Passwords come only from `read_password`."""

    read_line: Callable[[str], str] = input
    read_password: Callable[[str], str] = getpass.getpass
    is_tty: Callable[[], bool] = _stdin_is_tty
    write: Callable[[str], None] = _write
    error: Callable[[str], None] = _error

    def need_terminal(self, what: str) -> None:
        """Refuse (exit 2) when input is needed but stdin is not a terminal."""
        if not self.is_tty():
            msg = f"{what} needs an interactive terminal (stdin is not a TTY)."
            raise CliError(msg, code=2)

    def confirm(self, question: str, *, yes: bool) -> bool:
        """Ask a yes/no question; `yes` (``--yes``) answers it without asking."""
        if yes:
            return True
        self.need_terminal("Confirming (or pass --yes)")
        return self.read_line(f"{question} [y/N] ").strip().lower() in {"y", "yes"}
