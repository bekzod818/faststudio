"""commit-msg hook: enforce Conventional Commits (https://www.conventionalcommits.org)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
PATTERN = re.compile(rf"^({'|'.join(TYPES)})(\([a-z0-9._/-]+\))?!?: \S.{{0,98}}$")


def is_valid(subject: str) -> bool:
    """Return True when ``subject`` is a valid Conventional Commit header."""
    return bool(PATTERN.match(subject)) or subject.startswith(("Merge ", "Revert ", "fixup! "))


def main(argv: list[str]) -> int:
    """Validate the first line of the commit message file in ``argv[0]``."""
    subject = Path(argv[0]).read_text(encoding="utf-8").splitlines()[0] if argv else ""
    if is_valid(subject):
        return 0
    print(f"Commit subject is not a Conventional Commit: {subject!r}")
    print(f"Expected '<type>(<scope>)?: <description>' with type in {', '.join(TYPES)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
