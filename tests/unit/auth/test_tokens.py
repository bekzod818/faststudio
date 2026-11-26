"""Signed session cookies and CSRF tokens."""

from __future__ import annotations

import secrets

import pytest

from faststudio.auth.csrf import CsrfTokens
from faststudio.auth.session import SessionData, SessionManager


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def secret() -> str:
    return secrets.token_urlsafe(48)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sessions(secret: str, clock: Clock) -> SessionManager:
    return SessionManager(secret, max_age=3600, clock=clock)


def test_session_round_trip(sessions: SessionManager) -> None:
    value = sessions.issue(user_id="42", auth_version="v1")[0]
    data = sessions.load(value)
    assert data is not None
    assert (data.user_id, data.auth_version) == ("42", "v1")
    assert len(data.session_id) >= 20


def test_each_session_gets_a_fresh_id(sessions: SessionManager) -> None:
    first = sessions.load(sessions.issue(user_id="1", auth_version="v")[0])
    second = sessions.load(sessions.issue(user_id="1", auth_version="v")[0])
    assert first is not None
    assert second is not None
    assert first.session_id != second.session_id


@pytest.mark.parametrize("tamper", ["flip", "truncate", "empty", "garbage", "other-key"])
def test_tampered_session_is_rejected(sessions: SessionManager, secret: str, tamper: str) -> None:
    value = sessions.issue(user_id="42", auth_version="v1")[0]
    if tamper == "flip":
        value = value[:-2] + ("A" if value[-2] != "A" else "B") + value[-1]
    elif tamper == "truncate":
        value = value[: len(value) // 2]
    elif tamper == "empty":
        value = ""
    elif tamper == "garbage":
        value = "not.a.cookie"
    else:
        value = SessionManager(secrets.token_urlsafe(48), max_age=3600).issue(
            user_id="42", auth_version="v1"
        )[0]
    assert sessions.load(value) is None


def test_session_expires(sessions: SessionManager, clock: Clock) -> None:
    value = sessions.issue(user_id="42", auth_version="v1")[0]
    clock.now += 3599
    assert sessions.load(value) is not None
    clock.now += 2
    assert sessions.load(value) is None


def test_session_from_the_future_is_rejected(sessions: SessionManager, clock: Clock) -> None:
    value = sessions.issue(user_id="42", auth_version="v1")[0]
    clock.now -= 600
    assert sessions.load(value) is None


def test_session_payload_is_not_readable_as_secret(sessions: SessionManager, secret: str) -> None:
    assert secret not in sessions.issue(user_id="42", auth_version="v1")[0]


def test_session_and_csrf_keys_are_separate(secret: str) -> None:
    session_value = SessionManager(secret, max_age=60).issue(user_id="1", auth_version="v")[0]
    csrf = CsrfTokens(secret)
    assert not csrf.verify(session_value, session_id=None)


def test_anonymous_csrf_token(secret: str) -> None:
    csrf = CsrfTokens(secret)
    token = csrf.issue(session_id=None)
    assert csrf.verify(token, session_id=None)
    assert not csrf.verify(token, session_id="sid-1")


def test_session_bound_csrf_token(secret: str) -> None:
    csrf = CsrfTokens(secret)
    token = csrf.issue(session_id="sid-1")
    assert csrf.verify(token, session_id="sid-1")
    assert not csrf.verify(token, session_id="sid-2")
    assert not csrf.verify(token, session_id=None)


def test_csrf_tokens_are_unique(secret: str) -> None:
    csrf = CsrfTokens(secret)
    assert csrf.issue(session_id=None) != csrf.issue(session_id=None)


@pytest.mark.parametrize(
    "token", ["", ".", "abc", "a.b.c", "nonce.", ".mac", "x" * 5000, "nonce.éé"]
)
def test_malformed_csrf_tokens_are_rejected(secret: str, token: str) -> None:
    assert not CsrfTokens(secret).verify(token, session_id=None)


def test_csrf_token_from_other_secret_is_rejected(secret: str) -> None:
    other = CsrfTokens(secrets.token_urlsafe(48)).issue(session_id=None)
    assert not CsrfTokens(secret).verify(other, session_id=None)


def test_session_data_repr_hides_ids() -> None:
    data = SessionData(
        user_id="42", auth_version="secret-av", session_id="secret-sid", issued_at=1, seen=1
    )
    assert "secret-sid" not in repr(data)
    assert "secret-av" not in repr(data)


@pytest.mark.parametrize(
    "payload", [["only-one"], ["1", "v", "sid", "not-an-int"], {"uid": "1"}, ["1", 2, "s", 3]]
)
def test_signed_but_malformed_payload_is_rejected(
    sessions: SessionManager, payload: object
) -> None:
    forged = sessions._serializer.dumps(payload)
    assert sessions.load(forged) is None


def test_issue_returns_the_data_it_signed(sessions: SessionManager) -> None:
    value, data = sessions.issue(user_id="7", auth_version="v")
    assert sessions.load(value) == data


def test_session_signature_uses_sha256(secret: str) -> None:
    """Changing the digest after release would sign everyone out: pin it."""
    manager = SessionManager(secret, max_age=60)
    value, _ = manager.issue(user_id="1", auth_version="v")
    signature = value.rsplit(".", 1)[1]
    assert len(signature) == 43  # base64url of a 32-byte HMAC-SHA256 digest
