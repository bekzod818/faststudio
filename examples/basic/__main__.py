"""Run the example: ``python -m examples.basic [--host H] [--port P] [--ephemeral]``.

``--ephemeral`` uses a throwaway database that is deleted on exit and, when
FASTSTUDIO_EXAMPLE_ADMIN_USERNAME and FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD are
set, creates that admin at startup. It is meant for demos and the E2E suite.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import uvicorn

from examples.basic.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m examples.basic", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="throwaway database; admin from FASTSTUDIO_EXAMPLE_ADMIN_* variables",
    )
    args = parser.parse_args(argv)

    if not args.ephemeral:
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0

    username = os.environ.get("FASTSTUDIO_EXAMPLE_ADMIN_USERNAME")
    password = os.environ.get("FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD")
    bootstrap = (username, password) if username and password else None
    if bootstrap is None:
        print(
            "No FASTSTUDIO_EXAMPLE_ADMIN_USERNAME/PASSWORD set: nobody can sign in.",
            file=sys.stderr,
        )
    with tempfile.TemporaryDirectory(prefix="faststudio-example-") as workdir:
        app = create_app(f"sqlite+aiosqlite:///{workdir}/example.db", bootstrap_admin=bootstrap)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
