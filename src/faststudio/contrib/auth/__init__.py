"""Users, groups and permissions for the admin (ADR-0011 §8).

`AuthModels(Base)` declares the tables on your declarative base;
`DatabaseAuthBackend(models)` signs admin staff in, grants permissions
(superusers hold all) and registers the users, groups and permissions
admins. These are **admin staff accounts**: every active user can sign in to
the admin, so never store your application's end users in these tables.
"""

from faststudio.auth.validators import (
    DEFAULT_VALIDATORS,
    CommonPasswordValidator,
    MinimumLengthValidator,
    NumericPasswordValidator,
    PasswordValidator,
    UserAttributeSimilarityValidator,
)
from faststudio.contrib.auth.admins import group_admin, permission_admin, user_admin
from faststudio.contrib.auth.backend import DatabaseAuthBackend
from faststudio.contrib.auth.models import AuthModels, normalize_username

__all__ = [
    "DEFAULT_VALIDATORS",
    "AuthModels",
    "CommonPasswordValidator",
    "DatabaseAuthBackend",
    "MinimumLengthValidator",
    "NumericPasswordValidator",
    "PasswordValidator",
    "UserAttributeSimilarityValidator",
    "group_admin",
    "normalize_username",
    "permission_admin",
    "user_admin",
]
