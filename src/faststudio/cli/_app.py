"""Resolve ``--app module.path:attr`` to an `Admin` (ADR-0012 §2).

The target is an `Admin`, a FastAPI application with exactly one `Admin`
mounted, or a zero-argument factory returning either. The application's
lifespan never runs: the CLI imports and builds, it does not start the app.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from faststudio.admin import Admin, mounted_admins
from faststudio.cli._io import CliError
from faststudio.exceptions import ConfigurationError


def _failed(spec: str, exc: Exception) -> str:
    # The type only: messages can hold connection URLs or other configuration.
    module = spec.partition(":")[0]
    return (
        f"Cannot load {spec} ({type(exc).__name__}). Run "
        f'`python -c "import {module}"` to see the error.'
    )


_NOT_A_TARGET = "is not a faststudio.Admin, a FastAPI app or a factory of one."


def load_admin(spec: str) -> Admin:
    """Resolve `spec` (``module.path:attr``) to the `Admin` it names."""
    target = _import(spec)
    if not isinstance(target, Admin | FastAPI) and callable(target):
        target = _call_factory(spec, target)
    if isinstance(target, FastAPI):
        return _the_mounted_admin(spec, target)
    if not isinstance(target, Admin):
        msg = f"{spec} {_NOT_A_TARGET}"
        raise CliError(msg, code=2)
    return target


def _import(spec: str) -> object:
    """Import the module of `spec` and return its attribute."""
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
    return target


def _call_factory(spec: str, factory: Callable[[], object]) -> object:
    """Call a zero-argument factory; it must return an `Admin` or a FastAPI app.

    Whatever the factory does when called runs (the app's lifespan does not).
    """
    try:
        inspect.signature(factory).bind()
    except TypeError:  # it needs arguments: not a factory
        msg = f"{spec} {_NOT_A_TARGET}"
        raise CliError(msg, code=2) from None
    except ValueError:  # no signature (some builtins): just try calling it
        pass
    try:
        result = factory()
    except ConfigurationError as exc:
        raise CliError(f"Cannot load {spec}: {exc}", code=2) from None
    except Exception as exc:  # a bug in the factory, e.g. a TypeError inside it
        msg = f"Calling {spec}() failed ({type(exc).__name__})."
        raise CliError(msg, code=2) from None
    if not isinstance(result, Admin | FastAPI):
        msg = f"{spec} returned {type(result).__name__}, not a faststudio.Admin or a FastAPI app."
        raise CliError(msg, code=2)
    return result


def _the_mounted_admin(spec: str, app: FastAPI) -> Admin:
    admins = mounted_admins(app)
    if len(admins) == 1:
        return admins[0]
    if not admins:
        msg = (
            f"{spec} has no faststudio.Admin mounted (an Admin created in the app's "
            "lifespan is not seen: point --app at the Admin itself)."
        )
        raise CliError(msg, code=2)
    listed = ", ".join(
        f"{admin._settings.base_url} ({admin._settings.title!r})" for admin in admins
    )
    msg = (
        f"{len(admins)} faststudio.Admin instances are mounted on {spec}: {listed}; "
        "point --app at the one you mean (module.path:admin)."
    )
    raise CliError(msg, code=2)
