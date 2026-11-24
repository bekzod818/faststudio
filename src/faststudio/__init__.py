"""FastStudio: a modern, beautiful admin studio for FastAPI."""

from faststudio.admin import Admin
from faststudio.auth.backend import AuthBackend, AuthenticatedUser
from faststudio.auth.model_backend import ModelUserBackend
from faststudio.auth.passwords import hash_password
from faststudio.exceptions import ConfigurationError, FastStudioError
from faststudio.model_admin import ModelAdmin
from faststudio.security.rate_limit import InMemoryRateLimiter, RateLimitDecision, RateLimiter

__version__ = "0.1.0"

__all__ = [
    "Admin",
    "AuthBackend",
    "AuthenticatedUser",
    "ConfigurationError",
    "FastStudioError",
    "InMemoryRateLimiter",
    "ModelAdmin",
    "ModelUserBackend",
    "RateLimitDecision",
    "RateLimiter",
    "__version__",
    "hash_password",
]
