"""Resolved, validated FastStudio settings (private; not public API)."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta

from faststudio.exceptions import ConfigurationError
from faststudio.security.secret import resolve_secret_key

logger = logging.getLogger("faststudio")

API_PREFIX = "/api/v1"
MAX_TITLE_LENGTH = 100
MIN_SESSION_MAX_AGE = timedelta(seconds=60)
MAX_PAGE_SIZE_LIMIT = 1000
#: Default and largest allowed `max_list_offset` (rows an OFFSET may skip).
DEFAULT_MAX_LIST_OFFSET = 10_000
MAX_LIST_OFFSET_LIMIT = 10_000_000
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")


def normalize_base_url(raw: object) -> str:
    """Validate a mount path and return it without a trailing slash.

    Accepts ``/segment[/segment...]`` where segments use unreserved URL
    characters only. Rejects the root path, empty or dot segments, queries,
    fragments, percent-encoding and absolute URLs. The result is safe to use
    as a cookie ``Path`` and inside ``<base href>``.
    """
    if not isinstance(raw, str):
        msg = f"base_url must be a str, got {type(raw).__name__}."
        raise ConfigurationError(msg)
    path = raw[:-1] if raw.endswith("/") and len(raw) > 1 else raw
    segments = path.split("/")
    valid = (
        path.startswith("/")
        and len(segments) > 1
        and all(_SEGMENT.fullmatch(s) and s not in {".", ".."} for s in segments[1:])
    )
    if not valid:
        msg = (
            f"Invalid base_url {raw!r}: expected a path like '/admin' made of letters, "
            "digits, '.', '_', '~' and '-' (the root path '/' is not allowed)."
        )
        raise ConfigurationError(msg)
    return path


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated configuration shared by all FastStudio components."""

    secret_key: str = field(repr=False)
    title: str
    base_url: str
    session_max_age: timedelta
    secure_cookies: bool
    max_page_size: int
    #: Lists never skip this many rows or more (OFFSET); see query/_params.py.
    max_list_offset: int
    show_powered_by: bool
    #: Sessions also end after this long without a request (ADR-0013); None = off.
    session_idle_timeout: timedelta | None = None

    @property
    def api_url(self) -> str:
        """Absolute path of the JSON API, e.g. ``/admin/api/v1``."""
        return f"{self.base_url}{API_PREFIX}"


def _require_type(name: str, value: object, expected: type) -> None:
    # bool is a subclass of int; never accept True/False where a number is expected.
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        msg = f"{name} must be {expected.__name__}, got {type(value).__name__}."
        raise ConfigurationError(msg)


def _duration(name: str, value: object) -> timedelta:
    """Normalize int seconds or a timedelta (never bool) and check the minimum."""
    if isinstance(value, timedelta):
        duration = value
    elif isinstance(value, int) and not isinstance(value, bool):
        duration = timedelta(seconds=value)
    else:
        msg = f"{name} must be int seconds or timedelta, got {type(value).__name__}."
        raise ConfigurationError(msg)
    if duration < MIN_SESSION_MAX_AGE:
        msg = f"{name} must be at least {MIN_SESSION_MAX_AGE.total_seconds():.0f} seconds."
        raise ConfigurationError(msg)
    return duration


def resolve_settings(
    *,
    secret_key: str | None,
    title: str,
    base_url: str,
    session_max_age: int | timedelta,
    secure_cookies: bool,
    max_page_size: int,
    max_list_offset: int,
    show_powered_by: bool,
    session_idle_timeout: int | timedelta | None = None,
) -> Settings:
    """Validate raw options and return :class:`Settings`.

    Raises:
        ConfigurationError: on any invalid option, including wrong types.

    """
    _require_type("title", title, str)
    max_age = _duration("session_max_age", session_max_age)
    idle = (
        None
        if session_idle_timeout is None
        else _duration("session_idle_timeout", session_idle_timeout)
    )
    _require_type("secure_cookies", secure_cookies, bool)
    _require_type("max_page_size", max_page_size, int)
    _require_type("max_list_offset", max_list_offset, int)
    _require_type("show_powered_by", show_powered_by, bool)
    clean_title = title.strip()
    if not clean_title or len(clean_title) > MAX_TITLE_LENGTH:
        msg = f"title must be 1-{MAX_TITLE_LENGTH} characters."
        raise ConfigurationError(msg)
    if any(unicodedata.category(ch) in {"Cc", "Cf"} for ch in clean_title):
        msg = "title must not contain control or invisible formatting characters."
        raise ConfigurationError(msg)
    if idle is not None and idle > max_age:
        msg = "session_idle_timeout must not exceed session_max_age."
        raise ConfigurationError(msg)
    if not 1 <= max_page_size <= MAX_PAGE_SIZE_LIMIT:
        msg = f"max_page_size must be between 1 and {MAX_PAGE_SIZE_LIMIT}."
        raise ConfigurationError(msg)
    if not 1 <= max_list_offset <= MAX_LIST_OFFSET_LIMIT:
        msg = f"max_list_offset must be between 1 and {MAX_LIST_OFFSET_LIMIT}."
        raise ConfigurationError(msg)
    settings = Settings(
        secret_key=resolve_secret_key(secret_key),
        title=clean_title,
        base_url=normalize_base_url(base_url),
        session_max_age=max_age,
        session_idle_timeout=idle,
        secure_cookies=secure_cookies,
        max_page_size=max_page_size,
        max_list_offset=max_list_offset,
        show_powered_by=show_powered_by,
    )
    if not secure_cookies:
        logger.warning(
            "FastStudio is running with secure_cookies=False: session cookies will be sent "
            "over plain HTTP. Never use this in production."
        )
    return settings
