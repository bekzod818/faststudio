import base64
import random
import secrets
import string
from collections.abc import Callable

import pytest

from faststudio import ConfigurationError
from faststudio.security.secret import (
    MIN_HANDWRITTEN_SECRET_LENGTH,
    MIN_SECRET_LENGTH,
    resolve_secret_key,
)

ENV = "FASTSTUDIO_SECRET_KEY"


def test_explicit_strong_secret_is_returned() -> None:
    key = secrets.token_urlsafe(48)
    assert resolve_secret_key(key) == key


def test_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv(ENV, key)
    assert resolve_secret_key(None) == key


def test_explicit_value_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = secrets.token_urlsafe(48)
    monkeypatch.setenv(ENV, secrets.token_urlsafe(48))
    assert resolve_secret_key(explicit) == explicit


def test_explicit_empty_does_not_fall_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, secrets.token_urlsafe(48))
    with pytest.raises(ConfigurationError, match="missing"):
        resolve_secret_key("")


@pytest.mark.parametrize("env_value", [None, ""])
def test_missing_secret_fails(monkeypatch: pytest.MonkeyPatch, env_value: str | None) -> None:
    if env_value is not None:
        monkeypatch.setenv(ENV, env_value)
    with pytest.raises(ConfigurationError, match=ENV) as exc_info:
        resolve_secret_key(None)
    assert "secrets.token_urlsafe" in str(exc_info.value)


@pytest.mark.parametrize("value", [b"x" * 48, 12345, ["k"]])
def test_non_str_secret_fails_without_echoing(value: object) -> None:
    with pytest.raises(ConfigurationError, match="must be a str") as exc_info:
        resolve_secret_key(value)
    assert repr(value) not in str(exc_info.value)


def test_too_short_fails() -> None:
    key = secrets.token_urlsafe(48)[: MIN_SECRET_LENGTH - 1]
    with pytest.raises(ConfigurationError, match=f"at least {MIN_SECRET_LENGTH}"):
        resolve_secret_key(key)


@pytest.mark.parametrize("key", ["ab" * 32, "0a1b2c3d4" * 5, "éè" * 20])
def test_low_diversity_fails(key: str) -> None:
    with pytest.raises(ConfigurationError, match="too predictable"):
        resolve_secret_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "abcdefghijklmnopqrstuvwxyz0123456789",
        "asdfghjkl" + secrets.token_urlsafe(32),
        "0123456789" * 4,
        "ZYXWVUTSRQ" + secrets.token_urlsafe(32),
        secrets.token_urlsafe(32) + "98765432",
    ],
)
def test_sequential_or_keyboard_runs_fail(key: str) -> None:
    with pytest.raises(ConfigurationError, match="sequential"):
        resolve_secret_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "changeme-" + secrets.token_urlsafe(32),
        "CHANGE_ME_" + secrets.token_urlsafe(32),
        "your-secret-key-" + secrets.token_urlsafe(32),
        secrets.token_urlsafe(32) + "-insecure",
        "replace-me-" + secrets.token_urlsafe(32),
        "my-super-secret-key-for-faststudio-admin-panel",
        "my-super-secure-faststudio-admin-2026!",
        "my-super-secure-admin-key-2026!-x7#Kq9@Lm2$Wp4",  # short markers, hand-written charset
        "Placeholder" + secrets.token_urlsafe(32),
        "example" + secrets.token_urlsafe(32),
        "password" + secrets.token_urlsafe(32),
    ],
)
def test_placeholder_secret_fails(key: str) -> None:
    with pytest.raises(ConfigurationError, match="placeholder"):
        resolve_secret_key(key)


def test_keyboard_row_with_digits_fails() -> None:
    # Reported in review: a full keyboard-row key must never pass.
    with pytest.raises(ConfigurationError, match=r"placeholder|sequential"):
        resolve_secret_key("qwertyuiopasdfghjklzxcvbnm123456")


@pytest.mark.parametrize("marker", ["admin", "super", "secure", "qwerty", "Admin"])
def test_short_markers_inside_random_text_are_ignored(marker: str) -> None:
    # Avoids false rejections of random keys that happen to contain them mid-token.
    key = secrets.token_hex(16) + marker + secrets.token_hex(16)
    assert resolve_secret_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        # Reported in review: hyphenated phrases look like a generated charset.
        "my-super-secure-admin-key-for-prod-2026",
        "super-secure-admin-panel-key-2026-prod-v2",
        "admin_" + secrets.token_urlsafe(40),
        secrets.token_hex(20) + "-Admin",
    ],
)
def test_short_markers_as_whole_words_fail(key: str) -> None:
    with pytest.raises(ConfigurationError, match="placeholder"):
        resolve_secret_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "correct-horse-battery-staple-orange-violet",  # 42 chars
        "Correct-Horse-Battery-Staple-Orange-Violet",  # title case, 42 chars
        "glacier_mountain_river_forest_7429_ocean",
    ],
)
def test_short_passphrase_fails(key: str) -> None:
    assert len(key) < MIN_HANDWRITTEN_SECRET_LENGTH
    with pytest.raises(ConfigurationError, match="hand-written"):
        resolve_secret_key(key)


def test_long_passphrase_is_accepted() -> None:
    key = "correct-horse-battery-staple-orange-violet-lantern-9"
    assert resolve_secret_key(key) == key


def test_short_handwritten_secret_fails() -> None:
    key = "Tr0ub4dor&3!horse#battery$stapl9"  # 32 chars with symbols
    assert len(key) < MIN_HANDWRITTEN_SECRET_LENGTH
    with pytest.raises(ConfigurationError, match="hand-written"):
        resolve_secret_key(key)


def test_long_secret_with_symbols_is_accepted() -> None:
    key = "Tr0ub4dor&3!horse#battery$stapl9-gr8%v1ew*k7m"
    assert len(key) >= MIN_HANDWRITTEN_SECRET_LENGTH
    assert resolve_secret_key(key) == key


@pytest.mark.parametrize("key", [" " + secrets.token_urlsafe(48), secrets.token_urlsafe(48) + "\n"])
def test_surrounding_whitespace_fails(key: str) -> None:
    with pytest.raises(ConfigurationError, match="whitespace"):
        resolve_secret_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "short",
        "ab" * 32,
        "changeme-" + secrets.token_urlsafe(32),
        " " + secrets.token_urlsafe(48),
        "abcdefghijklmnopqrstuvwxyz0123456789",
        "Tr0ub4dor&3!horse#battery$stapl9",
    ],
)
def test_error_message_never_contains_the_secret(key: str) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_secret_key(key)
    message = str(exc_info.value)
    assert key.strip() not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


# --- False-positive guard: keys from real generators must always be accepted.
# A fixed seed keeps this deterministic; the distribution matches the secrets module.
_RNG = random.Random(20261123)
_DJANGO_CHARS = string.ascii_lowercase + string.digits + "!@#$%^&*(-_=+)"


def _generated_keys() -> list[str]:
    keys: list[str] = []
    for _ in range(500):
        raw = _RNG.randbytes(48)
        keys.append(base64.urlsafe_b64encode(raw).rstrip(b"=").decode())  # token_urlsafe(48)
        keys.append(_RNG.randbytes(32).hex())  # token_hex(32)
        keys.append(base64.b64encode(raw).decode())  # openssl rand -base64 48
        keys.append("".join(_RNG.choice(_DJANGO_CHARS) for _ in range(50)))  # Django-style
    return keys


def test_generated_keys_are_accepted() -> None:
    rejected = []
    for key in _generated_keys():
        try:
            resolve_secret_key(key)
        except ConfigurationError:
            rejected.append(key)
    assert rejected == []


@pytest.mark.parametrize(
    "factory", [lambda: secrets.token_urlsafe(48), lambda: secrets.token_hex(32)]
)
def test_secrets_module_keys_are_accepted(factory: Callable[[], str]) -> None:
    key = factory()
    assert resolve_secret_key(key) == key
