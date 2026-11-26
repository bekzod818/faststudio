"""Idle timeout and sliding refresh of session cookies (ADR-0013, M20)."""

from __future__ import annotations

import hashlib

import pytest
from itsdangerous import URLSafeSerializer

from faststudio.auth.session import SessionManager

SECRET = "s" * 48
HOUR = 3600


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _payload(value: str) -> list[object]:
    serializer = URLSafeSerializer(
        SECRET, salt="faststudio.session", signer_kwargs={"digest_method": hashlib.sha256}
    )
    data: list[object] = serializer.loads(value)
    return data


def test_without_idle_timeout_the_cookie_is_the_v0_1_format() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=8 * HOUR, clock=clock)
    value, data = manager.issue(user_id="7", auth_version="av")
    assert _payload(value) == ["7", "av", data.session_id, 1_000_000]
    # Byte for byte what v0.1 signed for the same payload.
    v01 = URLSafeSerializer(
        SECRET, salt="faststudio.session", signer_kwargs={"digest_method": hashlib.sha256}
    ).dumps(["7", "av", data.session_id, 1_000_000])
    assert value == v01
    assert manager.refresh_due(data) is False


def test_with_idle_timeout_the_cookie_carries_last_seen() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=8 * HOUR, idle_timeout=HOUR, clock=clock)
    value, data = manager.issue(user_id="7", auth_version="av")
    assert _payload(value) == ["7", "av", data.session_id, 1_000_000, 1_000_000]
    loaded = manager.load(value)
    assert loaded is not None
    assert loaded.seen == 1_000_000


def test_old_four_item_cookies_load_with_seen_at_issue_time() -> None:
    clock = Clock()
    plain = SessionManager(SECRET, max_age=8 * HOUR, clock=clock)
    value, _ = plain.issue(user_id="7", auth_version="av")
    idle = SessionManager(SECRET, max_age=8 * HOUR, idle_timeout=HOUR, clock=clock)
    loaded = idle.load(value)
    assert loaded is not None
    assert loaded.seen == loaded.issued_at
    clock.now += HOUR + 1
    assert idle.load(value) is None  # idle since issue


def test_idle_expiry_boundary_and_sliding_refresh() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=8 * HOUR, idle_timeout=HOUR, clock=clock)
    value, data = manager.issue(user_id="7", auth_version="av")
    clock.now += 5 * 60 - 1
    assert manager.refresh_due(data) is False  # min(timeout / 4, 5 min) not reached
    clock.now += 1
    assert manager.refresh_due(data) is True
    refreshed = manager.refresh(data)
    again = manager.load(refreshed)
    assert again is not None
    assert (again.session_id, again.issued_at, again.seen) == (
        data.session_id,
        data.issued_at,
        int(clock.now),
    )
    clock.now += HOUR
    assert manager.load(refreshed) is not None  # exactly the timeout: still valid
    clock.now += 1
    assert manager.load(refreshed) is None
    assert manager.load(value) is None


def test_short_timeouts_refresh_after_a_quarter() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=HOUR, idle_timeout=120, clock=clock)
    _, data = manager.issue(user_id="7", auth_version="av")
    clock.now += 29
    assert manager.refresh_due(data) is False
    clock.now += 1
    assert manager.refresh_due(data) is True


def test_absolute_expiry_still_applies_after_refreshes() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=2 * HOUR, idle_timeout=HOUR, clock=clock)
    _, data = manager.issue(user_id="7", auth_version="av")
    value = ""
    for _ in range(5):
        clock.now += 30 * 60
        value = manager.refresh(data)
        loaded = manager.load(value)
        if loaded is None:
            break
        data = loaded
    assert clock.now - data.issued_at > 2 * HOUR
    assert manager.load(value) is None
    assert manager.remaining(data) == 0


def test_remaining_lifetime_never_exceeds_max_age() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=2 * HOUR, idle_timeout=HOUR, clock=clock)
    _, data = manager.issue(user_id="7", auth_version="av")
    clock.now -= 30  # another worker's clock is behind: the issue time is "in the future"
    assert manager.remaining(data) == 2 * HOUR


def test_remaining_lifetime() -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=2 * HOUR, idle_timeout=HOUR, clock=clock)
    _, data = manager.issue(user_id="7", auth_version="av")
    clock.now += 600
    assert manager.remaining(data) == 2 * HOUR - 600


@pytest.mark.parametrize(
    "payload",
    [
        ["7", "av", "sid", 1_000_000, 999_999],  # seen before issued_at
        ["7", "av", "sid", 1_000_000, -1],  # never coerced into the issue time
        ["7", "av", "sid", 1_000_000, 1_000_000 + 61],  # seen beyond the allowed skew
        ["7", "av", "sid", 1_000_000, "1000000"],  # wrong type
        ["7", "av", "sid", 1_000_000, True],  # bool is not an int here
        ["7", "av", "sid", 1_000_000, 1_000_000, 1],  # six items
        ["7", "av", "sid"],
    ],
)
def test_malformed_payloads_are_refused(payload: list[object]) -> None:
    clock = Clock()
    manager = SessionManager(SECRET, max_age=8 * HOUR, idle_timeout=HOUR, clock=clock)
    serializer = URLSafeSerializer(
        SECRET, salt="faststudio.session", signer_kwargs={"digest_method": hashlib.sha256}
    )
    assert manager.load(serializer.dumps(payload)) is None


def test_five_item_cookies_still_load_when_the_timeout_is_turned_off() -> None:
    clock = Clock()
    idle = SessionManager(SECRET, max_age=8 * HOUR, idle_timeout=HOUR, clock=clock)
    value, _ = idle.issue(user_id="7", auth_version="av")
    clock.now += 2 * HOUR
    plain = SessionManager(SECRET, max_age=8 * HOUR, clock=clock)
    assert plain.load(value) is not None  # only the absolute expiry applies
