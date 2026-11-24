"""argon2id password hashing (threat model T2)."""

from __future__ import annotations

import threading

import pytest

from faststudio import hash_password
from faststudio.auth import passwords
from faststudio.auth.passwords import (
    dummy_verify,
    dummy_verify_async,
    is_password_hash,
    verify_password,
    verify_password_async,
)


def test_hash_is_argon2id_and_salted() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2id$")
    assert first != second
    assert "correct horse" not in first


def test_verify_accepts_correct_password() -> None:
    assert verify_password(hash_password("s3cret-pass"), "s3cret-pass")


@pytest.mark.parametrize("candidate", ["wrong", "", "s3cret-pass ", "S3CRET-PASS"])
def test_verify_rejects_wrong_password(candidate: str) -> None:
    assert not verify_password(hash_password("s3cret-pass"), candidate)


@pytest.mark.parametrize(
    "stored", ["", "not-a-hash", "$2b$12$bcrypt", "plaintext", "$argon2id$broken"]
)
def test_verify_never_raises_on_malformed_hash(stored: str) -> None:
    assert not verify_password(stored, "anything")


def test_hash_password_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        hash_password("")


def test_dummy_verify_runs_a_real_verification() -> None:
    assert dummy_verify("whatever") is False


@pytest.mark.parametrize("value", [None, "", "plain", 42, "$2b$12$x"])
def test_is_password_hash_rejects_unusable_values(value: object) -> None:
    assert is_password_hash(value) is False


def test_is_password_hash_accepts_argon2() -> None:
    assert is_password_hash(hash_password("pw"))


async def test_async_verification_runs_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """argon2 is CPU-heavy: it must not block the loop shared with the host app."""
    threads: list[threading.Thread] = []
    real = passwords.verify_password

    def recording(stored: str, password: str) -> bool:
        threads.append(threading.current_thread())
        return real(stored, password)

    monkeypatch.setattr(passwords, "verify_password", recording)
    stored = hash_password("s3cret-pass")
    assert await verify_password_async(stored, "s3cret-pass")
    assert not await verify_password_async(stored, "wrong")
    assert not await dummy_verify_async("anything")
    assert len(threads) == 3
    assert all(thread is not threading.main_thread() for thread in threads)


async def test_concurrent_verifications_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """At most MAX_CONCURRENT_VERIFICATIONS argon2 runs at once; the rest queue."""
    import time  # noqa: PLC0415

    import anyio  # noqa: PLC0415

    lock = threading.Lock()
    running = peak = 0

    def slow(stored: str, password: str) -> bool:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1
        return False

    monkeypatch.setattr(passwords, "verify_password", slow)
    async with anyio.create_task_group() as group:
        for _ in range(3 * passwords.MAX_CONCURRENT_VERIFICATIONS):
            group.start_soon(verify_password_async, "hash", "pw")
    assert peak == passwords.MAX_CONCURRENT_VERIFICATIONS
