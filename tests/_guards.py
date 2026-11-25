"""Reach a backend's account guard capability in tests (ADR-0011)."""

from __future__ import annotations

from faststudio.auth.guard import AccountGuard, FlagAccountGuard


def guard_of(backend: object) -> FlagAccountGuard:
    """Return the `FlagAccountGuard` a backend such as `ModelUserBackend` provides."""
    guard: AccountGuard | None = backend.faststudio_capabilities.account_guard  # type: ignore[attr-defined]
    assert isinstance(guard, FlagAccountGuard)
    return guard
