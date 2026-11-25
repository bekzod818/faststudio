"""Authorization for API routes (ADR-0011 §4-5; threat model T9).

Every model route depends on `resolve_permissions`, which resolves the
signed-in admin's permissions once per request (0 queries without a
permission backend). Routes then ask the ModelAdmin hooks through `allowed`
or `require`. A hook that returns anything but ``True`` refuses (fail closed).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, Request

from faststudio.api._deps import DbSession
from faststudio.api.auth import CurrentUser, get_context
from faststudio.api.errors import ApiError
from faststudio.auth.capabilities import ALL, AllPermissions, Permissions
from faststudio.auth.permissions import cache_permissions
from faststudio.registry import RegisteredModel

Action = Literal["view", "create", "edit", "delete"]

#: `request.state` attribute caching the identities the admin may view.
_VIEWABLE_KEY = "faststudio_viewable"


async def resolve_permissions(
    request: Request, session: DbSession, user: CurrentUser
) -> Permissions:
    """Resolve and cache the signed-in admin's permissions (once per request)."""
    backend = get_context(request).capabilities.permissions
    perms: object = ALL if backend is None else await backend.resolve(session, user)
    if not isinstance(perms, AllPermissions) and not (
        isinstance(perms, frozenset) and all(isinstance(c, str) for c in perms)
    ):
        msg = "PermissionBackend.resolve() must return ALL or a frozenset of codenames."
        raise TypeError(msg)  # a backend bug: 500, never a guess
    cache_permissions(request, perms)
    return perms


#: Declared by every model route (the route-enumeration test checks it).
Perms = Annotated[Permissions, Depends(resolve_permissions)]


async def allowed(
    request: Request, registered: RegisteredModel, action: Action, obj: object | None = None
) -> bool:
    """Ask the ModelAdmin hook for `action` (object-level when `obj` is given)."""
    admin_class = registered.admin_class
    if action == "create":
        result: object = await admin_class.has_create_permission(request)
    elif action == "view":
        result = await admin_class.has_view_permission(request, obj)
    elif action == "edit":
        result = await admin_class.has_edit_permission(request, obj)
    else:
        result = await admin_class.has_delete_permission(request, obj)
    return result is True


async def require(
    request: Request, registered: RegisteredModel, action: Action, obj: object | None = None
) -> None:
    """Raise `403 forbidden` unless the hook allows `action`."""
    if not await allowed(request, registered, action, obj):
        raise ApiError(403, "forbidden")


async def viewable(request: Request) -> frozenset[str]:
    """Identities of the models the admin may view (model level), cached per request."""
    cached: frozenset[str] | None = getattr(request.state, _VIEWABLE_KEY, None)
    if cached is not None:
        return cached
    result = frozenset(
        [
            registered.identity
            for registered in get_context(request).registry
            if await allowed(request, registered, "view")
        ]
    )
    setattr(request.state, _VIEWABLE_KEY, result)
    return result
