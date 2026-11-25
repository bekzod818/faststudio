"""Password validators (ADR-0011 §8; threat model T2).

Validators check a new password and return a message for the admin, or
``None`` when they accept it. `validate_password` always applies FastStudio's
hard limits first (not empty, at most `MAX_PASSWORD_LENGTH` characters, no
NUL), then each validator in order, and returns every message.

FastStudio bundles no common-password list: no list with a clearly
permissive licence was found (plan amendment A5). Use
`CommonPasswordValidator` with a list file you are licensed to use.
"""

from __future__ import annotations

import gzip
import unicodedata
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from faststudio.exceptions import ConfigurationError
from faststudio.schemas.contract import MAX_PASSWORD_LENGTH

__all__ = [
    "DEFAULT_VALIDATORS",
    "CommonPasswordValidator",
    "MinimumLengthValidator",
    "NumericPasswordValidator",
    "PasswordValidator",
    "UserAttributeSimilarityValidator",
    "validate_password",
]

#: Parts of a user input shorter than this are not compared (e.g. "al").
_MIN_PART_LENGTH = 3
_SEPARATORS = "@._-+ "
_MIN_SIMILARITY = 0.1
_SIMILAR = "Make the password less similar to the account's name or email."


@runtime_checkable
class PasswordValidator(Protocol):
    """Checks a new password; `user_inputs` are the account's name, email and similar."""

    def validate(self, password: str, *, user_inputs: Sequence[str]) -> str | None:
        """Return a message for the admin, or ``None`` if `password` is acceptable."""
        ...


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _folded(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


class MinimumLengthValidator:
    """At least `min_length` characters (code points after NFC normalization)."""

    def __init__(self, min_length: int = 12) -> None:
        """Raise `ConfigurationError` unless `min_length` is a positive int."""
        value: object = min_length  # untyped callers
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            msg = "MinimumLengthValidator: min_length must be a positive int."
            raise ConfigurationError(msg)
        self.min_length = min_length

    def validate(self, password: str, *, user_inputs: Sequence[str]) -> str | None:
        """Refuse passwords shorter than `min_length`."""
        del user_inputs
        if len(_normalized(password)) < self.min_length:
            return f"Use at least {self.min_length} characters."
        return None


class NumericPasswordValidator:
    """Not only digits (in any script)."""

    def validate(self, password: str, *, user_inputs: Sequence[str]) -> str | None:
        """Refuse passwords made only of decimal digits."""
        del user_inputs
        return "Do not use only digits." if password.isdecimal() else None


class UserAttributeSimilarityValidator:
    """Not too similar to the account's name, email or similar inputs.

    Compares case-folded text. A password is refused when it contains a
    whole input, or the local part of an email address (before ``@``), of
    at least 3 characters; or when its similarity ratio with the input or
    with one of its parts (split on ``@ . _ - +`` and spaces, at least 3
    characters) reaches `max_similarity`. Parts are not checked for
    containment, so an email's domain (``example``, ``com``) does not rule
    out ordinary passphrases.
    """

    def __init__(self, max_similarity: float = 0.7) -> None:
        """Raise `ConfigurationError` unless `max_similarity` is between 0.1 and 1."""
        value: object = max_similarity  # untyped callers
        if not isinstance(value, (int, float)) or not _MIN_SIMILARITY <= value <= 1:
            msg = "UserAttributeSimilarityValidator: max_similarity must be between 0.1 and 1."
            raise ConfigurationError(msg)
        self.max_similarity = float(max_similarity)

    @staticmethod
    def _parts(folded: str) -> list[str]:
        parts, part = [], ""
        for char in folded:
            if char in _SEPARATORS:
                parts.append(part)
                part = ""
            else:
                part += char
        return [*parts, part]

    def _similar(self, password: str, value: str) -> bool:
        matcher = SequenceMatcher(a=password, b=value)
        return (
            matcher.quick_ratio() >= self.max_similarity and matcher.ratio() >= self.max_similarity
        )

    def validate(self, password: str, *, user_inputs: Sequence[str]) -> str | None:
        """Refuse passwords that contain or closely resemble a user input."""
        folded = _folded(password)
        for raw in user_inputs:
            value = _folded(raw)
            contained = [value, value.split("@", 1)[0]] if "@" in value else [value]
            if any(len(c) >= _MIN_PART_LENGTH and c in folded for c in contained):
                return _SIMILAR
            candidates = [value, *self._parts(value)]
            if any(len(c) >= _MIN_PART_LENGTH and self._similar(folded, c) for c in candidates):
                return _SIMILAR
        return None


class CommonPasswordValidator:
    """Not in a list of common passwords you provide (FastStudio bundles none).

    `path` is a UTF-8 text file, optionally gzip-compressed (``.gz``), with
    one password per line; surrounding whitespace and empty lines are
    ignored, and the comparison is case-insensitive.
    """

    def __init__(self, path: str | Path) -> None:
        """Load the list now, so a missing file fails at startup.

        Raises:
            ConfigurationError: if the file cannot be read.

        """
        file = Path(path)
        try:
            raw = file.read_bytes()
            if file.suffix == ".gz":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8")
        except (OSError, EOFError, UnicodeDecodeError, gzip.BadGzipFile) as exc:
            msg = f"CommonPasswordValidator: cannot read {file} ({type(exc).__name__})."
            raise ConfigurationError(msg) from None
        self.passwords: frozenset[str] = frozenset(
            _folded(line.strip()) for line in text.splitlines() if line.strip()
        )

    def validate(self, password: str, *, user_inputs: Sequence[str]) -> str | None:
        """Refuse passwords on the list."""
        del user_inputs
        return "This password is too common." if _folded(password) in self.passwords else None


#: Used when a backend is given no validators.
DEFAULT_VALIDATORS: Final[tuple[PasswordValidator, ...]] = (
    MinimumLengthValidator(12),
    UserAttributeSimilarityValidator(),
    NumericPasswordValidator(),
)


def validate_password(
    password: str, validators: Iterable[PasswordValidator], *, user_inputs: Sequence[str]
) -> list[str]:
    """Return every reason to refuse `password` (empty if it is acceptable).

    FastStudio's hard limits are checked first and always apply; when one
    fails, its message is returned alone.
    """
    if not password:
        return ["Enter a password."]
    if len(password) > MAX_PASSWORD_LENGTH:
        return [f"Use at most {MAX_PASSWORD_LENGTH} characters."]
    if "\x00" in password:
        return ["Remove the NUL character."]
    messages = []
    for validator in validators:
        message = validator.validate(password, user_inputs=user_inputs)
        if message is not None:
            messages.append(message)
    return messages
