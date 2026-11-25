"""Resolve ``--app module.path:attr`` to an `Admin` (ADR-0012 §2)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from faststudio.admin import Admin
from faststudio.cli._io import CliError
from faststudio.exceptions import ConfigurationError


def _failed(spec: str, exc: Exception) -> str:
    # The type only: messages can hold connection URLs or other configuration.
    module = spec.partition(":")[0]
    return (
        f"Cannot load {spec} ({type(exc).__name__}). Run "
        f'`python -c "import {module}"` to see the error.'
    )


def load_admin(spec: str) -> Admin:
    """Import `spec` (``module.path:attr``): an `Admin` or a factory returning one."""
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        msg = f"--app must look like module.path:attr, got {spec!r}."
        raise CliError(msg, code=2)
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)  # like uvicorn: modules next to where you run it
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        msg = f"Cannot import {module_name!r} ({exc.name} not found)."
        raise CliError(msg, code=2) from None
    except ConfigurationError as exc:  # e.g. FASTSTUDIO_SECRET_KEY not set: safe to show
        raise CliError(f"Cannot load {spec}: {exc}", code=2) from None
    except Exception as exc:
        raise CliError(_failed(spec, exc), code=2) from None
    target: object = module
    for part in attr.split("."):
        if not hasattr(target, part):
            msg = f"{module_name!r} has no attribute {attr!r}."
            raise CliError(msg, code=2)
        target = getattr(target, part)
    if not isinstance(target, Admin) and callable(target):
        try:
            target = target()
        except TypeError:  # e.g. a FastAPI app, which is callable but not a factory
            msg = f"{spec} is not a faststudio.Admin (or a factory returning one)."
            raise CliError(msg, code=2) from None
        except ConfigurationError as exc:
            raise CliError(f"Cannot load {spec}: {exc}", code=2) from None
        except Exception as exc:
            raise CliError(_failed(spec, exc), code=2) from None
    if not isinstance(target, Admin):
        msg = f"{spec} is not a faststudio.Admin (or a factory returning one)."
        raise CliError(msg, code=2)
    return target
