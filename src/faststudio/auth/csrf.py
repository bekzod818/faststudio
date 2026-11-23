"""Signed double-submit CSRF tokens (threat model T3)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

CSRF_COOKIE = "faststudio_csrftoken"
CSRF_HEADER = "x-faststudio-csrf"
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
_MAC = re.compile(r"[A-Za-z0-9_-]{43}")
_MAX_TOKEN_LENGTH = 128


class CsrfTokens:
    """Tokens are `nonce.mac` where mac = HMAC-SHA256(key, context|nonce).

    The context is `anon` before login and the session id afterwards, so a
    token only works for the session it was issued to. The key is derived from
    the secret with a purpose label, separate from session signing.
    """

    def __init__(self, secret_key: str) -> None:
        """Derive the CSRF key from the FastStudio secret."""
        self._key = hmac.new(secret_key.encode(), b"faststudio.csrf", hashlib.sha256).digest()

    def _mac(self, nonce: str, session_id: str | None) -> str:
        context = "anon" if session_id is None else f"sid:{session_id}"
        digest = hmac.new(self._key, f"{context}|{nonce}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def issue(self, *, session_id: str | None) -> str:
        """Return a new token bound to `session_id` (or anonymous)."""
        nonce = secrets.token_urlsafe(16)
        return f"{nonce}.{self._mac(nonce, session_id)}"

    def verify(self, token: str, *, session_id: str | None) -> bool:
        """Return True if `token` was issued by us for exactly this session (or anonymous)."""
        if len(token) > _MAX_TOKEN_LENGTH:
            return False
        nonce, sep, mac = token.partition(".")
        if not sep or not _NONCE.fullmatch(nonce) or not _MAC.fullmatch(mac):
            return False
        return hmac.compare_digest(mac.encode(), self._mac(nonce, session_id).encode())
