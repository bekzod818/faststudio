"""Default `ModelAdmin` classes for the contrib models (customizable).

They are factories because the model classes exist only after
`AuthModels(Base)`. To customize, turn off the automatic registration and
register subclasses::

    backend = DatabaseAuthBackend(auth, register_admins=False)
    admin = Admin(app, engine=engine, auth_backend=backend)

    class StaffAdmin(user_admin(auth)):
        list_display = ("id", "username", "email", "last_login")

    admin.register(StaffAdmin)
    admin.register(group_admin(auth))
    admin.register(permission_admin(auth))

Subclasses must keep ``password_hash`` and ``session_token`` excluded:
registration fails otherwise.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from faststudio import ModelAdmin

if TYPE_CHECKING:
    from faststudio.contrib.auth.models import AuthModels

__all__ = ["group_admin", "permission_admin", "user_admin"]

#: Never shown or accepted by the admin (enforced at `register()`).
SECRET_FIELDS = ("password_hash", "session_token")
#: `permissions` fields hold up to this many codenames (A3).
_PERMISSION_LIMIT = MappingProxyType({"permissions": 10_000})  # the documented maximum


def user_admin(models: AuthModels) -> type[ModelAdmin]:
    """Return the default admin class for users (subclass it to customize)."""

    class UserAdmin(ModelAdmin, model=models.user):
        name = "User"
        icon = "users"
        list_display = ("id", "username", "email", "is_active", "is_superuser")
        search_fields = ("username", "email")
        list_filter = ("is_active", "is_superuser")
        ordering = ("username",)
        exclude = (*SECRET_FIELDS, "username_normalized")
        readonly_fields = ("date_joined", "last_login")
        many_to_many = ("groups", "permissions")
        many_to_many_limits = _PERMISSION_LIMIT

    return UserAdmin


def group_admin(models: AuthModels) -> type[ModelAdmin]:
    """Return the default admin class for groups (subclass it to customize)."""

    class GroupAdmin(ModelAdmin, model=models.group):
        name = "Group"
        icon = "users-round"
        list_display = ("id", "name")
        search_fields = ("name",)
        ordering = ("name",)
        many_to_many = ("permissions",)
        many_to_many_limits = _PERMISSION_LIMIT

    return GroupAdmin


def permission_admin(models: AuthModels) -> type[ModelAdmin]:
    """Return the default, read-only admin class for permissions.

    Permissions follow the registered models (``faststudio syncpermissions``,
    v0.2), so they are not created, edited or deleted here.
    """

    class PermissionAdmin(ModelAdmin, model=models.permission):
        name = "Permission"
        icon = "key-round"
        list_display = ("id", "codename", "name")
        search_fields = ("codename", "name")
        ordering = ("codename",)
        can_create = False
        can_edit = False
        can_delete = False

    return PermissionAdmin
