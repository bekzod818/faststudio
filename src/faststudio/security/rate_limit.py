"""Pluggable login rate limiting (threat model T2)."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Result of one login attempt.

    Attributes:
        allowed: Whether the attempt may proceed.
        retry_after: Seconds until another attempt may succeed; at least 1 when
            `allowed` is False, 0 otherwise. Sent as the `Retry-After` header.

    """

    allowed: bool
    retry_after: int = 0


@runtime_checkable
class RateLimiter(Protocol):
    """Counts login attempts per key (client IP + username).

    Implement this protocol to share limits across processes (e.g. Redis).
    """

    async def hit(self, key: str) -> RateLimitDecision:
        """Record an attempt for `key` and say whether it is allowed.

        Implementations should record only allowed attempts (so a lockout does
        not extend itself) and return `retry_after >= 1` when refusing.
        """
        ...

    async def reset(self, key: str) -> None:
        """Forget attempts for `key` (after a successful login)."""
        ...


class InMemoryRateLimiter:
    """Sliding-window limiter kept in process memory.

    Suitable for a single process. With several workers each has its own
    counters, so use a shared implementation of `RateLimiter` instead.
    Rejected attempts are not recorded, so a lockout does not extend itself.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: int = 900,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Allow `max_attempts` per key within `window_seconds`; keep at most `max_keys` keys."""
        for name, value in (
            ("max_attempts", max_attempts),
            ("window_seconds", window_seconds),
            ("max_keys", max_keys),
        ):
            if value < 1:
                msg = f"{name} must be at least 1"
                raise ValueError(msg)
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()

    async def hit(self, key: str) -> RateLimitDecision:
        """Record an attempt unless the key is over its limit."""
        now = self._clock()
        attempts = self._attempts.get(key)
        if attempts is None:
            if len(self._attempts) >= self._max_keys:
                self._attempts.popitem(last=False)  # evict the least recently used key
            attempts = self._attempts[key] = deque()
        self._attempts.move_to_end(key)
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            return RateLimitDecision(False, max(1, math.ceil(attempts[0] + self._window - now)))
        attempts.append(now)
        return RateLimitDecision(True)

    async def reset(self, key: str) -> None:
        """Forget all attempts for `key`."""
        self._attempts.pop(key, None)
