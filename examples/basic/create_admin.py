"""Create an admin account (or reset its password).

    python -m examples.basic.create_admin USERNAME

The password is read interactively (twice). Uses the same database as the
app (FASTSTUDIO_EXAMPLE_DATABASE_URL, default ./example.db).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from examples.basic.app import DEFAULT_DATABASE_URL
from examples.basic.db import MIN_PASSWORD_LENGTH, create_or_update_admin, create_tables


async def _run(database_url: str, username: str, password: str) -> bool:
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        await create_tables(engine)
        return await create_or_update_admin(
            async_sessionmaker(engine, expire_on_commit=False), username, password
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m examples.basic.create_admin")
    parser.add_argument("username")
    args = parser.parse_args(argv)

    password = getpass.getpass(f"Password (at least {MIN_PASSWORD_LENGTH} characters): ")
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    url = os.environ.get("FASTSTUDIO_EXAMPLE_DATABASE_URL", DEFAULT_DATABASE_URL)
    try:
        created = asyncio.run(_run(url, args.username, password))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        # The type only: driver messages can echo parameters.
        print(f"Could not save the admin ({type(error).__name__}).", file=sys.stderr)
        return 1
    print(f"{'Created' if created else 'Updated'} admin {args.username!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
