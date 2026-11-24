"""argon2id password hashing (threat model T2)."""

from __future__ import annotations

from functools import lru_cache

import anyio
from anyio.lowlevel import RunVar
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()  # argon2id with argon2-cffi's current recommended parameters

#: Concurrent argon2 verifications per event loop. Each one costs tens of
#: milliseconds of CPU and ~64 MiB of memory; more are queued, not refused.
MAX_CONCURRENT_VERIFICATIONS = 4
_LIMITER: RunVar[anyio.CapacityLimiter] = RunVar("faststudio_password_limiter")


def hash_password(password: str) -> str:
    """Hash `password` with argon2id for storing in your user table.

    Use it to create or reset admin accounts read by `ModelUserBackend`.

    Raises:
        ValueError: if `password` is empty.

    """
    if not password:
        msg = "password must not be empty"
        raise ValueError(msg)
    return _HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Return True if `password` matches `stored_hash`; never raises on bad input."""
    try:
        return _HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def is_password_hash(value: object) -> bool:
    """Return True if `value` is an argon2 hash this module can verify."""
    if not isinstance(value, str) or not value:
        return False
    try:
        extract_parameters(value)
    except (InvalidHashError, ValueError):
        return False
    return True


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash("faststudio-timing-equalizer")


def prepare_dummy_hash() -> None:
    """Compute the dummy hash now so the first failed login is not slower."""
    _dummy_hash()


def dummy_verify(password: str) -> bool:
    """Spend the same time as a real verification (unknown usernames); always False."""
    verify_password(_dummy_hash(), password + "\x00not-the-dummy")
    return False


def _limiter() -> anyio.CapacityLimiter:
    try:
        return _LIMITER.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(MAX_CONCURRENT_VERIFICATIONS)
        _LIMITER.set(limiter)
        return limiter


async def verify_password_async(stored_hash: str, password: str) -> bool:
    """`verify_password` in a worker thread, so login never blocks the event loop."""
    return await anyio.to_thread.run_sync(
        verify_password, stored_hash, password, limiter=_limiter()
    )


async def dummy_verify_async(password: str) -> bool:
    """`dummy_verify` in a worker thread; always False."""
    return await anyio.to_thread.run_sync(dummy_verify, password, limiter=_limiter())
