"""Hatch build hook: guarantee the pre-built SPA ships inside every wheel (ADR-0002)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_ESCAPE_HATCH = "FASTSTUDIO_ALLOW_MISSING_FRONTEND"


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    """Fail the wheel build when ``src/faststudio/static/index.html`` is missing."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        index = Path(self.root) / "src" / "faststudio" / "static" / "index.html"
        if index.is_file():
            return
        # Editable installs never ship to users, so a missing SPA is fine there.
        if version == "editable" or os.environ.get(_ESCAPE_HATCH) == "1":
            self.app.display_warning(
                f"FastStudio SPA not built ({index} missing); building without it."
            )
            return
        msg = (
            f"FastStudio SPA not found at {index}.\n"
            "Run `pnpm -C frontend install && pnpm -C frontend build` first, "
            f"or set {_ESCAPE_HATCH}=1 for a development-only build."
        )
        raise RuntimeError(msg)
