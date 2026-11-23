"""Pluggable login rate limiting (threat model T2)."""

from __future__ import annotations

import pytest

from faststudio import InMemoryRateLimiter, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_allows_up_to_limit_then_blocks() -> None:
    clock = Clock()
    limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60, clock=clock)
    decisions = [await limiter.hit("k") for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[-1].retry_after == 60


async def test_window_slides() -> None:
    clock = Clock()
    limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=60, clock=clock)
    await limiter.hit("k")
    clock.now += 30
    await limiter.hit("k")
    blocked = await limiter.hit("k")
    assert not blocked.allowed
    assert blocked.retry_after == 30
    clock.now += 31
    assert (await limiter.hit("k")).allowed


async def test_keys_are_independent_and_reset_works() -> None:
    limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60, clock=Clock())
    assert (await limiter.hit("a")).allowed
    assert (await limiter.hit("b")).allowed
    assert not (await limiter.hit("a")).allowed
    await limiter.reset("a")
    assert (await limiter.hit("a")).allowed


async def test_memory_is_bounded() -> None:
    limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60, max_keys=10, clock=Clock())
    for i in range(50):
        await limiter.hit(f"key{i}")
    assert len(limiter._attempts) <= 10


@pytest.mark.parametrize("option", ["max_attempts", "window_seconds", "max_keys"])
def test_invalid_configuration(option: str) -> None:
    kwargs = {"max_attempts": 1, "window_seconds": 1, "max_keys": 1}
    kwargs[option] = 0
    with pytest.raises(ValueError, match=f"{option} must be"):
        InMemoryRateLimiter(
            max_attempts=kwargs["max_attempts"],
            window_seconds=kwargs["window_seconds"],
            max_keys=kwargs["max_keys"],
        )


def test_satisfies_protocol() -> None:
    assert isinstance(InMemoryRateLimiter(), RateLimiter)
