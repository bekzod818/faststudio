"""FastStudio: a modern, beautiful admin studio for FastAPI."""

from faststudio.admin import Admin
from faststudio.auth.backend import AuthBackend, AuthenticatedUser
from faststudio.auth.capabilities import ALL, BackendCapabilities
from faststudio.auth.guard import FlagAccountGuard
from faststudio.auth.model_backend import ModelUserBackend
from faststudio.auth.passwords import hash_password
from faststudio.auth.permissions import has_perm
from faststudio.exceptions import ConfigurationError, FastStudioError
from faststudio.model_admin import ModelAdmin
from faststudio.security.rate_limit import InMemoryRateLimiter, RateLimitDecision, RateLimiter

__version__ = "0.1.2.dev0"

__all__ = [
    "ALL",
    "Admin",
    "AuthBackend",
    "AuthenticatedUser",
    "BackendCapabilities",
    "ConfigurationError",
    "FastStudioError",
    "FlagAccountGuard",
    "InMemoryRateLimiter",
    "ModelAdmin",
    "ModelUserBackend",
    "RateLimitDecision",
    "RateLimiter",
    "__version__",
    "has_perm",
    "hash_password",
]
