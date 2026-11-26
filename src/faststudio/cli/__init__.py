"""The ``faststudio`` command line (ADR-0012).

Commands: ``createadmin``, ``changepassword``, ``syncpermissions`` and
``checkusers``, each with ``--app module.path:attr`` naming an `Admin`, a
FastAPI application with one `Admin` mounted, or a zero-argument factory
returning either. Passwords are only ever read from an
interactive prompt, twice; ``--yes`` answers confirmations, never passwords.

Exit codes: 0 success, 1 the command refused or failed, 2 usage error (bad
arguments, ``--app`` not found, input needed without a terminal).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio.admin import Admin
from faststudio.cli._app import load_admin
from faststudio.cli._commands import COMMANDS
from faststudio.cli._io import CliError, CliIO

__all__ = ["CliIO", "main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faststudio", description="FastStudio admin commands.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        sub.add_argument(
            "--app",
            required=True,
            metavar="MODULE:ATTR",
            help=(
                "the Admin, the FastAPI app it is mounted on, or a zero-argument "
                "factory of either, e.g. main:admin or main:create_app"
            ),
        )
        return sub

    create = command("createadmin", "Create an admin account with every permission.")
    create.add_argument("--username", help="the new account's username (prompted if omitted)")
    create.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="a text column of the user model (repeatable), e.g. --set email=ann@example.com",
    )
    change = command("changepassword", "Set an account's password (signs it out everywhere).")
    change.add_argument("username")
    sync = command("syncpermissions", "Create permissions for the registered models.")
    sync.add_argument("--dry-run", action="store_true", help="only report what would change")
    sync.add_argument(
        "--prune", action="store_true", help="also delete stale permissions and their grants"
    )
    sync.add_argument("--yes", action="store_true", help="do not ask before deleting")
    check = command("checkusers", "Check normalized usernames (and repair them with --fix).")
    check.add_argument("--fix", action="store_true", help="repair mismatches that do not collide")
    check.add_argument("--yes", action="store_true", help="do not ask before repairing")
    return parser


def main(argv: Sequence[str] | None = None, *, io: CliIO | None = None) -> int:
    """Run the CLI and return its exit code (tests pass `io` instead of a terminal)."""
    terminal = io or CliIO()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # --help (0) or a usage error (2); argparse printed it
        return int(exc.code or 0)
    try:
        admin = load_admin(args.app)
        return asyncio.run(_run(admin, args, terminal))
    except (CliError, EOFError, KeyboardInterrupt, SQLAlchemyError) as exc:
        message, code = _failure(exc)
        terminal.error(message)
        return code


def _failure(exc: BaseException) -> tuple[str, int]:
    """Map an expected failure to its message and exit code (no internals)."""
    if isinstance(exc, CliError):
        return str(exc), exc.code
    if isinstance(exc, EOFError):  # Ctrl-D at a prompt
        return "Aborted: nothing was changed.", 1
    if isinstance(exc, KeyboardInterrupt):  # Ctrl-C
        return "Interrupted: nothing was changed.", 130
    if isinstance(exc, (OperationalError, ProgrammingError)):
        return (
            f"Database error ({type(exc).__name__}). If the tables do not exist yet, run "
            "your migrations (or Base.metadata.create_all) first.",
            1,
        )
    return f"Database error ({type(exc).__name__}). Nothing was changed.", 1


async def _run(admin: Admin, args: argparse.Namespace, terminal: CliIO) -> int:
    try:
        return await COMMANDS[args.command](admin, args, terminal)
    finally:
        # Close the engine's connections inside this event loop, before it ends.
        options = admin._session_maker.kw
        engines = [options.get("bind"), *options.get("binds", {}).values()]
        for engine in {id(e): e for e in engines if isinstance(e, AsyncEngine)}.values():
            await engine.dispose()


def console_main() -> None:
    """Entry point of the ``faststudio`` console script."""
    sys.exit(main())
