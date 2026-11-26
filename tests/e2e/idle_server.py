"""Test-only launcher for the Playwright idle-timeout test (M20). Never packaged.

Runs the example app with ``session_idle_timeout=60`` and a session clock the
E2E test can move forward through ``POST /__e2e__/advance?seconds=N`` on the
*host* app. The clock is injected from here, through the `SessionManager`
the admin built; `faststudio` itself has no such hook
(tests/unit/test_no_test_hooks.py).

    uv run python tests/e2e/idle_server.py --port 4174

Needs FASTSTUDIO_SECRET_KEY and FASTSTUDIO_EXAMPLE_ADMIN_USERNAME/PASSWORD,
like ``python -m examples.basic --ephemeral``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root

import examples.basic.app as example
from faststudio import Admin

IDLE_TIMEOUT = 60


class AdvanceableClock:
    """Real time plus an offset that only moves forward."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.time() + self.offset


def build(database_url: str, admin_user: tuple[str, str] | None) -> Any:
    """Return the example app with an idle timeout and an advanceable session clock."""
    built: list[Admin] = []

    class IdleAdmin(Admin):
        def __init__(self, app: Any, **options: Any) -> None:
            super().__init__(app, session_idle_timeout=IDLE_TIMEOUT, **options)
            built.append(self)

    example.__dict__["Admin"] = IdleAdmin  # create_app looks the name up at call time
    app = example.create_app(database_url, bootstrap_admin=admin_user)
    [admin] = built
    clock = AdvanceableClock()
    admin._sub_app.state.faststudio.sessions._clock = clock

    @app.post("/__e2e__/advance", include_in_schema=False)
    async def advance(seconds: int) -> dict[str, float]:
        clock.offset += max(0, seconds)
        return {"offset": clock.offset}

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4174)
    args = parser.parse_args()
    username = os.environ.get("FASTSTUDIO_EXAMPLE_ADMIN_USERNAME")
    password = os.environ.get("FASTSTUDIO_EXAMPLE_ADMIN_PASSWORD")
    admin_user = (username, password) if username and password else None
    with tempfile.TemporaryDirectory(prefix="faststudio-idle-e2e-") as workdir:
        app = build(f"sqlite+aiosqlite:///{workdir}/idle.db", admin_user)
        # Loopback only: the advance route must never be reachable from outside.
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
