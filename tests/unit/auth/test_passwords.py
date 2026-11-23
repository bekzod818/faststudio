"""argon2id password hashing (threat model T2)."""

from __future__ import annotations

import pytest

from faststudio import hash_password
from faststudio.auth.passwords import dummy_verify, is_password_hash, verify_password


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
