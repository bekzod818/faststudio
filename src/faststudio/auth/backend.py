"""Pluggable authentication backend protocol (ADR-0004)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from starlette.requests import Request

from faststudio.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """An admin user as seen by FastStudio.

    Attributes:
        id: Stable identifier stored in the session cookie.
        username: Display name shown in the UI.
        auth_version: Opaque, non-empty value that **must change** whenever the
            user's credentials or access change (for example derived from the
            password hash and active/admin flags). Sessions created with a
            different value are rejected, so a password change or deactivation
            signs the user out everywhere.

    Raises:
        ConfigurationError: if any field is not a non-empty string.

    """

    id: str
    username: str
    auth_version: str

    def __post_init__(self) -> None:
        """Reject empty identity fields; an empty auth_version disables revocation."""
        for name in ("id", "username", "auth_version"):
            value: object = getattr(self, name)
            if not isinstance(value, str) or not value:
                msg = f"AuthenticatedUser.{name} must be a non-empty str."
                raise ConfigurationError(msg)


@runtime_checkable
class AuthBackend(Protocol):
    """Authenticates admins and loads them for each request.

    FastStudio's core owns session cookies, CSRF protection, expiry and rate
    limiting; a backend only verifies credentials and looks users up. Both
    methods must be ``async``.

    Security requirements for implementations:

    * Return ``None`` for every failure (unknown user, wrong password,
      inactive, not an admin) without revealing which one.
    * Take the same time for unknown and known users, e.g. by verifying the
      password against a dummy hash when the user does not exist, so login
      timing cannot be used to enumerate usernames. ``ModelUserBackend`` is
      the reference implementation.
    """

    async def authenticate(
        self, request: Request, username: str, password: str
    ) -> AuthenticatedUser | None:
        """Return the user if the credentials are valid and the user may sign in."""
        ...

    async def get_user(self, request: Request, user_id: str) -> AuthenticatedUser | None:
        """Return the current user for a session, or ``None`` if they may no longer sign in."""
        ...
