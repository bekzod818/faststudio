"""FastStudio: a modern, beautiful admin studio for FastAPI."""

from faststudio.admin import Admin
from faststudio.auth.backend import AuthBackend, AuthenticatedUser
from faststudio.exceptions import ConfigurationError, FastStudioError
from faststudio.model_admin import ModelAdmin

__version__ = "0.1.0.dev0"

__all__ = [
    "Admin",
    "AuthBackend",
    "AuthenticatedUser",
    "ConfigurationError",
    "FastStudioError",
    "ModelAdmin",
    "__version__",
]
