"""Print the CHANGELOG.md section for one version (used for GitHub release notes).

Usage: python scripts/changelog_notes.py 0.1.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def extract(text: str, version: str) -> str:
    """Return the body of the ``## [version]`` section, or raise ``LookupError``."""
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        msg = f"version {version} not found in CHANGELOG.md"
        raise LookupError(msg)
    return match.group(1).strip() + "\n"


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        sys.stdout.write(extract(CHANGELOG.read_text(encoding="utf-8"), argv[0]))
    except LookupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
