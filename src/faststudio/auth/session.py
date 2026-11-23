"""Stateless signed session cookies (ADR-0004)."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from itsdangerous import BadData, URLSafeSerializer

SESSION_COOKIE = "faststudio_session"
_SALT = "faststudio.session"
# Tolerated clock skew for cookies issued "in the future" (multiple servers).
_MAX_SKEW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class SessionData:
    """The verified content of a session cookie."""

    user_id: str
    auth_version: str = field(repr=False)
    session_id: str = field(repr=False)
    issued_at: int


class SessionManager:
    """Issue and verify `faststudio_session` values.

    The payload is signed (HMAC-SHA256 via itsdangerous with a purpose-specific
    salt), not encrypted: it holds only the user id, the user's auth_version,
    a random session id and the issue time. Expiry is absolute.
    """

    def __init__(
        self,
        secret_key: str,
        *,
        max_age: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a manager; `max_age` is the absolute session lifetime in seconds."""
        self._serializer = URLSafeSerializer(
            secret_key, salt=_SALT, signer_kwargs={"digest_method": hashlib.sha256}
        )
        self.max_age = max_age
        self._clock = clock

    def issue(self, *, user_id: str, auth_version: str) -> tuple[str, SessionData]:
        """Return a new signed cookie value and its data, with a fresh random session id."""
        data = SessionData(user_id, auth_version, secrets.token_urlsafe(16), int(self._clock()))
        value: str = self._serializer.dumps(
            [data.user_id, data.auth_version, data.session_id, data.issued_at]
        )
        return value, data

    def load(self, value: str | None) -> SessionData | None:
        """Return the session if `value` is authentic and not expired, else None."""
        if not value:
            return None
        try:
            payload = self._serializer.loads(value)
        except BadData:
            return None
        if not (
            isinstance(payload, list)
            and len(payload) == 4  # noqa: PLR2004 - payload layout
            and all(isinstance(part, str) for part in payload[:3])
            and isinstance(payload[3], int)
        ):
            return None
        user_id, auth_version, session_id, issued_at = payload
        now = self._clock()
        if issued_at > now + _MAX_SKEW_SECONDS or now - issued_at > self.max_age:
            return None
        return SessionData(user_id, auth_version, session_id, issued_at)
