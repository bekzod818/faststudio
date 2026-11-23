"""Assert that a built wheel contains the bundled SPA and typing marker.

Usage: python scripts/verify_wheel.py dist/faststudio-*.whl
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED = ("faststudio/py.typed", "faststudio/static/index.html")


def verify(wheel: Path) -> list[str]:
    """Return a list of problems found in ``wheel`` (empty when valid)."""
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    problems = [f"missing {name}" for name in REQUIRED if name not in names]
    assets = [n for n in names if n.startswith("faststudio/static/assets/")]
    if not any(n.endswith(".js") for n in assets):
        problems.append("no JavaScript bundle under faststudio/static/assets/")
    if any(n.endswith(".map") for n in names):
        problems.append("source maps must not ship in the wheel")
    return problems


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 1:
        print(__doc__)
        return 2
    wheel = Path(argv[0])
    problems = verify(wheel)
    for problem in problems:
        print(f"ERROR: {wheel.name}: {problem}")
    if not problems:
        print(f"OK: {wheel.name} contains the FastStudio SPA")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
