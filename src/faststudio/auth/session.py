"""Stateless signed session cookies (ADR-0004, ADR-0013)."""

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
# A sliding refresh is due after min(idle_timeout / 4, this many seconds).
_MAX_REFRESH_INTERVAL = 5 * 60
_V01_ITEMS = 4  # [user_id, auth_version, session_id, issued_at]
_IDLE_ITEMS = 5  # ... + last seen, written only when an idle timeout is configured


@dataclass(frozen=True, slots=True)
class SessionData:
    """The verified content of a session cookie."""

    user_id: str
    auth_version: str = field(repr=False)
    session_id: str = field(repr=False)
    issued_at: int
    #: Last activity (refresh time); the issue time for v0.1-format cookies.
    seen: int


def new_session_token() -> str:
    """Return a random per-account session token (32 bytes, 43 URL-safe characters).

    Rotating an account's token ends all of its sessions (ADR-0013); used by
    `ModelUserBackend(session_token_field=...)` and `faststudio.contrib.auth`.
    """
    return secrets.token_urlsafe(32)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class SessionManager:
    """Issue and verify `faststudio_session` values.

    The payload is signed (HMAC-SHA256 via itsdangerous with a purpose-specific
    salt), not encrypted: it holds only the user id, the user's auth_version,
    a random session id and the issue time, plus the last-seen time when an
    idle timeout is configured. Expiry is absolute (`max_age` from issue);
    with `idle_timeout`, a session also ends after that long without a
    refresh. Without an idle timeout the cookie is exactly the v0.1 format.
    """

    def __init__(
        self,
        secret_key: str,
        *,
        max_age: int,
        idle_timeout: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a manager; times are in seconds."""
        self._serializer = URLSafeSerializer(
            secret_key, salt=_SALT, signer_kwargs={"digest_method": hashlib.sha256}
        )
        self.max_age = max_age
        self.idle_timeout = idle_timeout
        self._clock = clock

    def _dumps(self, data: SessionData) -> str:
        items: list[object] = [data.user_id, data.auth_version, data.session_id, data.issued_at]
        if self.idle_timeout is not None:
            items.append(data.seen)
        value: str = self._serializer.dumps(items)
        return value

    def issue(self, *, user_id: str, auth_version: str) -> tuple[str, SessionData]:
        """Return a new signed cookie value and its data, with a fresh random session id."""
        now = int(self._clock())
        data = SessionData(user_id, auth_version, secrets.token_urlsafe(16), now, now)
        return self._dumps(data), data

    def load(self, value: str | None) -> SessionData | None:
        """Return the session if `value` is authentic and not expired, else None."""
        data = self._parse(value)
        if data is None:
            return None
        now = self._clock()
        expired = (
            data.issued_at > now + _MAX_SKEW_SECONDS
            or now - data.issued_at > self.max_age
            or data.seen < data.issued_at
            or data.seen > now + _MAX_SKEW_SECONDS
            or (self.idle_timeout is not None and now - data.seen > self.idle_timeout)
        )
        return None if expired else data

    def _parse(self, value: str | None) -> SessionData | None:
        """Return the signed payload in either layout, without any time checks."""
        if not value:
            return None
        try:
            payload = self._serializer.loads(value)
        except BadData:
            return None
        if not (
            isinstance(payload, list)
            and len(payload) in {_V01_ITEMS, _IDLE_ITEMS}
            and all(isinstance(part, str) for part in payload[:3])
            and all(_is_int(part) for part in payload[3:])
        ):
            return None
        user_id, auth_version, session_id, issued_at = payload[:4]
        seen = payload[4] if len(payload) == _IDLE_ITEMS else issued_at
        return SessionData(user_id, auth_version, session_id, issued_at, seen)

    def refresh_due(self, data: SessionData) -> bool:
        """Return True if the cookie should slide (idle timeout only, never every request)."""
        if self.idle_timeout is None:
            return False
        interval = min(self.idle_timeout / 4, _MAX_REFRESH_INTERVAL)
        return self._clock() - data.seen >= interval

    def refresh(self, data: SessionData) -> str:
        """Return the cookie value with `seen` set to now (same session id and issue time)."""
        now = int(self._clock())
        return self._dumps(
            SessionData(data.user_id, data.auth_version, data.session_id, data.issued_at, now)
        )

    def remaining(self, data: SessionData) -> int:
        """Return the seconds left before the absolute expiry (the cookie's Max-Age)."""
        # Capped: an issue time slightly in the future (clock skew) must not
        # make the browser keep the cookie longer than max_age.
        return min(self.max_age, max(0, int(self.max_age - (self._clock() - data.issued_at))))
