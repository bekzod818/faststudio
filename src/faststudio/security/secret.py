"""Secret key resolution and strength validation (private; not public API).

The secret signs session cookies and CSRF tokens, so a weak value is a full
authentication bypass. FastStudio refuses to start without a strong one.
These checks catch common mistakes (placeholders, short, sequential or
hand-typed keys); they cannot prove randomness, so always generate the key.
Error messages never include the secret itself.
"""

from __future__ import annotations

import os
import re
import string

from faststudio.exceptions import ConfigurationError

# Name of the environment variable, not a secret value.
SECRET_ENV_VAR = "FASTSTUDIO_SECRET_KEY"  # noqa: S105  # nosec B105
MIN_SECRET_LENGTH = 32
# Keys using characters outside what random generators emit (base64, base64url,
# hex) are usually typed by hand, so they must be longer.
MIN_HANDWRITTEN_SECRET_LENGTH = 43
_MIN_DISTINCT_CHARS = 11
_MAX_SEQUENCE_RUN = 7
_GENERATED_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_+/=")
# Markers of 7+ characters are checked on every key: the chance of one appearing
# in a random key is negligible (< 1e-9).
_PLACEHOLDER_MARKERS = (
    "changeme",
    "yoursecret",
    "secretkey",
    "replaceme",
    "insecure",
    "placeholder",
    "example",
    "password",
    "default",
    "notsecret",
    "faststudio",
    "letmein",
)
# Short markers would occasionally match *inside* random keys (~1 in 300k), so
# they only count as whole words delimited by non-alphanumerics (or the key edge).
_SHORT_PLACEHOLDER_MARKERS = frozenset({"admin", "secure", "super", "qwerty"})
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")
# Three or more lower- or title-case words joined by '-'/'_' ("correct-horse-battery")
# indicate a hand-typed passphrase even though the charset looks generated.
_PASSPHRASE_WORD = re.compile(r"[A-Za-z][a-z]{2,}")
_MIN_PASSPHRASE_WORDS = 3
_SEQUENCES = (
    string.ascii_lowercase,
    string.digits,
    "1234567890",
    "qwertyuiopasdfghjklzxcvbnm",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
)
_HINT = (
    'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))" '
    f"and pass it as secret_key=... or set {SECRET_ENV_VAR}."
)


def _sequence_windows(length: int) -> frozenset[str]:
    windows: set[str] = set()
    for seq in _SEQUENCES:
        for candidate in (seq, seq[::-1]):
            windows.update(candidate[i : i + length] for i in range(len(candidate) - length + 1))
    return frozenset(windows)


_FORBIDDEN_RUNS = _sequence_windows(_MAX_SEQUENCE_RUN + 1)


def _has_sequence_run(key: str) -> bool:
    lowered = key.lower()
    size = _MAX_SEQUENCE_RUN + 1
    return any(lowered[i : i + size] in _FORBIDDEN_RUNS for i in range(len(lowered) - size + 1))


def _is_handwritten(key: str) -> bool:
    if not set(key) <= _GENERATED_ALPHABET:
        return True
    words = [w for w in re.split(r"[-_]+", key) if _PASSPHRASE_WORD.fullmatch(w)]
    return len(words) >= _MIN_PASSPHRASE_WORDS


def _has_placeholder(key: str) -> bool:
    lowered = key.lower()
    normalized = "".join(ch for ch in lowered if ch.isalnum())
    if any(marker in normalized for marker in _PLACEHOLDER_MARKERS):
        return True
    return any(word in _SHORT_PLACEHOLDER_MARKERS for word in _WORD_SPLIT.split(lowered))


def _fail(reason: str) -> ConfigurationError:
    return ConfigurationError(f"FastStudio secret key {reason}. {_HINT}")


def resolve_secret_key(value: object) -> str:
    """Return a validated secret key from ``value`` or ``FASTSTUDIO_SECRET_KEY``.

    ``value`` of ``None`` means "read the environment variable".

    Raises:
        ConfigurationError: if the secret is missing, not a string, padded with
            whitespace, too short, a placeholder, sequential, or too predictable.

    """
    key = os.environ.get(SECRET_ENV_VAR) if value is None else value
    if key is None or key == "":
        raise _fail("is missing")
    if not isinstance(key, str):
        msg = f"FastStudio secret key must be a str, got {type(key).__name__}."
        raise ConfigurationError(msg)
    if key != key.strip():
        raise _fail("has leading or trailing whitespace; check how it is loaded")
    if len(key) < MIN_SECRET_LENGTH:
        raise _fail(f"must be at least {MIN_SECRET_LENGTH} characters")
    if _has_placeholder(key):
        raise _fail("looks like a placeholder value")
    if _has_sequence_run(key):
        raise _fail("contains a sequential or keyboard-row run")
    if len(set(key)) < _MIN_DISTINCT_CHARS:
        raise _fail("is too predictable (too few distinct characters)")
    if _is_handwritten(key) and len(key) < MIN_HANDWRITTEN_SECRET_LENGTH:
        raise _fail(
            "looks hand-written (a passphrase or characters outside base64/hex) and must be "
            f"at least {MIN_HANDWRITTEN_SECRET_LENGTH} characters"
        )
    return key
