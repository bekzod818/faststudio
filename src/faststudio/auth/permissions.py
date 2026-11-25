"""Per-request permission checks for hooks and routes (ADR-0011 §3-4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request

from faststudio.auth.capabilities import ALL, Permissions, holds
from faststudio.exceptions import ConfigurationError

if TYPE_CHECKING:
    from faststudio.api._context import AdminContext

__all__ = ["has_perm"]

#: `request.state` attribute caching the signed-in user's permissions.
_STATE_KEY = "faststudio_permissions"


def cache_permissions(request: Request, perms: Permissions) -> None:
    """Remember the permissions resolved for this request (internal)."""
    setattr(request.state, _STATE_KEY, perms)


def cached_permissions(request: Request) -> Permissions:
    """Return the permissions resolved for this request.

    Raises:
        ConfigurationError: outside a FastStudio admin request, where nothing
            was resolved.

    """
    perms: Permissions | None = getattr(request.state, _STATE_KEY, None)
    if perms is None:
        msg = (
            "has_perm() works only during a FastStudio admin API request, for "
            "example in ModelAdmin permission hooks."
        )
        raise ConfigurationError(msg)
    return perms


async def has_perm(request: Request, codename: str) -> bool:
    """Return True if the signed-in admin holds `codename` (``"<identity>.<action>"``).

    ``"<identity>.view"`` is also granted by ``"<identity>.edit"``. Without a
    permission backend every admin holds every permission. Use it in
    ``ModelAdmin`` permission hooks; the permissions were resolved once for
    the request, so it runs no query.
    """
    return holds(cached_permissions(request), codename)


def _identity_of(request: Request, admin_class: type[Any]) -> str:
    context: AdminContext | None = getattr(request.app.state, "faststudio", None)
    if context is None:
        msg = "Permission hooks run only inside a mounted faststudio.Admin."
        raise ConfigurationError(msg)
    return context.registry.for_admin_class(admin_class).identity


async def model_permission(request: Request, admin_class: type[Any], action: str) -> bool:
    """Default hook result: the ModelAdmin's static flag AND ``<identity>.<action>``."""
    flag = {"create": "can_create", "edit": "can_edit", "delete": "can_delete"}.get(action)
    if flag is not None and getattr(admin_class, flag) is not True:
        return False
    perms = cached_permissions(request)
    return perms is ALL or holds(perms, f"{_identity_of(request, admin_class)}.{action}")
