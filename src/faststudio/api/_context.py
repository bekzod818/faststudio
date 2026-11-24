"""Shared state for request handling (private)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from faststudio.auth.backend import AuthBackend
from faststudio.auth.csrf import CsrfTokens
from faststudio.auth.session import SessionManager
from faststudio.config import Settings
from faststudio.registry import Registry
from faststudio.security.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class AdminContext:
    """Everything request handling needs; stored on `app.state.faststudio`."""

    settings: Settings
    registry: Registry
    session_maker: async_sessionmaker[AsyncSession]
    auth_backend: AuthBackend
    static_dir: Path
    sessions: SessionManager
    csrf: CsrfTokens
    rate_limiter: RateLimiter
    #: Per-client budget across all usernames (in-process; see api/auth.py).
    client_rate_limiter: RateLimiter
