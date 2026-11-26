"""Password validators (ADR-0011 §8, M18a)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from faststudio import ConfigurationError
from faststudio.auth.validators import (
    DEFAULT_VALIDATORS,
    CommonPasswordValidator,
    MinimumLengthValidator,
    NumericPasswordValidator,
    PasswordValidator,
    UserAttributeSimilarityValidator,
    validate_password,
)


def test_minimum_length() -> None:
    validator = MinimumLengthValidator(12)
    assert validator.validate("a" * 12, user_inputs=()) is None
    assert validator.validate("a" * 11, user_inputs=()) == "Use at least 12 characters."
    # Counted in code points after NFC, so composed and decomposed forms agree.
    assert validator.validate("é" * 10 + "x", user_inputs=()) == "Use at least 12 characters."


@pytest.mark.parametrize("bad", [0, -1, True, "12"])
def test_minimum_length_is_validated(bad: object) -> None:
    with pytest.raises(ConfigurationError, match="positive int"):
        MinimumLengthValidator(bad)  # type: ignore[arg-type]


def test_numeric() -> None:
    validator = NumericPasswordValidator()
    assert validator.validate("123456789012", user_inputs=()) == "Do not use only digits."
    assert validator.validate("١٢٣٤٥٦٧٨٩٠١٢", user_inputs=()) is not None  # other scripts' digits
    assert validator.validate("12345678901a", user_inputs=()) is None


@pytest.mark.parametrize(
    ("password", "inputs", "refused"),
    [
        ("alice-the-admin", ["alice"], True),  # contains the username
        ("ALICE2026!!xyz", ["alice"], True),  # case-folded
        ("Straße-Bahn-Fahrt", ["STRASSE"], True),  # full Unicode case folding
        ("alice@example.com", ["alice@example.com"], True),
        ("alice2026-rocks!", ["alice@example.com"], True),  # the email's local part
        ("examplx", ["alice@example.com"], True),  # very similar to a part
        ("examplepassword1", ["alice@example.com"], False),  # a domain part alone
        ("welcome to the jungle 77", ["alice@example.com"], False),  # contains "com"
        ("a long computer passphrase", ["bob@corp.com"], False),
        ("organic tea leaves forever", ["bob@mail.org"], False),
        ("correct horse battery", ["alice"], False),
        ("bob-is-my-friend", ["al"], False),  # parts shorter than 3 are ignored
        ("anything", [], False),
        ("anything at all", [""], False),
    ],
)
def test_similarity(password: str, inputs: list[str], *, refused: bool) -> None:
    message = UserAttributeSimilarityValidator().validate(password, user_inputs=inputs)
    assert (message is not None) is refused
    if refused:
        assert message == "Make the password less similar to the account's name or email."


def test_similarity_threshold_is_validated() -> None:
    with pytest.raises(ConfigurationError, match=r"between 0\.1 and 1"):
        UserAttributeSimilarityValidator(max_similarity=0)


def test_common_passwords_from_a_plain_file(tmp_path: Path) -> None:
    listing = tmp_path / "common.txt"
    listing.write_text("password\n\n  Dragon123  \n# not a comment\n", encoding="utf-8")
    validator = CommonPasswordValidator(listing)
    assert validator.validate("PASSWORD", user_inputs=()) == "This password is too common."
    assert validator.validate("dragon123", user_inputs=()) is not None
    assert validator.validate("# not a comment", user_inputs=()) is not None
    assert validator.validate("unusual words here", user_inputs=()) is None
    assert validator.validate("", user_inputs=()) is None  # empty lines are not entries


def test_common_passwords_from_a_gzip_file(tmp_path: Path) -> None:
    listing = tmp_path / "common.txt.gz"
    listing.write_bytes(gzip.compress(b"letmein\nqwerty\n"))
    assert CommonPasswordValidator(listing).validate("QWERTY", user_inputs=()) is not None


def test_common_passwords_need_a_readable_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot read"):
        CommonPasswordValidator(tmp_path / "missing.txt")


def test_defaults_and_ordering() -> None:
    assert [type(v) for v in DEFAULT_VALIDATORS] == [
        MinimumLengthValidator,
        UserAttributeSimilarityValidator,
        NumericPasswordValidator,
        CommonPasswordValidator,
    ]
    assert validate_password("1234", DEFAULT_VALIDATORS, user_inputs=["admin"]) == [
        "Use at least 12 characters.",
        "Do not use only digits.",
        "This password is too common.",
    ]
    assert validate_password("a long passphrase", DEFAULT_VALIDATORS, user_inputs=["bob"]) == []
    # Long enough, not similar, not numeric, but on the bundled list (A5).
    assert validate_password("1qaz2wsx3edc", DEFAULT_VALIDATORS, user_inputs=["bob"]) == [
        "This password is too common."
    ]


def test_the_bundled_list() -> None:
    """20 000 entries from zxcvbn (NOTICE), compared case-insensitively."""
    validator = CommonPasswordValidator()
    for common in ("password", "PassWord", "123456", "qwerty", "123qweasdzxc"):
        assert validator.validate(common, user_inputs=()) == "This password is too common."
    assert validator.validate("correct horse battery staple", user_inputs=()) is None
    assert len(validator.passwords) == 20_000


def test_the_bundled_list_is_loaded_once_and_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    from faststudio.auth import validators  # noqa: PLC0415

    validators._bundled_passwords.cache_clear()
    loads: list[int] = []
    real = validators._read_list

    def counting(path: object) -> frozenset[str]:
        loads.append(1)
        return real(path)  # type: ignore[arg-type]

    monkeypatch.setattr(validators, "_read_list", counting)
    first, second = CommonPasswordValidator(), CommonPasswordValidator()
    assert loads == []  # importing FastStudio or building defaults reads nothing
    first.validate("x", user_inputs=())
    second.validate("y", user_inputs=())
    assert loads == [1]
    validators._bundled_passwords.cache_clear()


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("", "Enter a password."),
        ("x" * 1025, "Use at most 1024 characters."),
        ("nul\x00inside-the-password", "Remove the NUL character."),
    ],
)
def test_hard_limits_always_apply(password: str, message: str) -> None:
    """Whatever the validators (even none), these are refused first."""
    assert validate_password(password, (), user_inputs=()) == [message]


def test_validators_are_a_protocol() -> None:
    assert isinstance(MinimumLengthValidator(), PasswordValidator)

    class Custom:
        def validate(self, password: str, *, user_inputs: object) -> str | None:
            del user_inputs
            return "No vowels allowed." if any(c in "aeiou" for c in password) else None

    assert isinstance(Custom(), PasswordValidator)
    assert validate_password("hello there", [Custom()], user_inputs=()) == ["No vowels allowed."]
