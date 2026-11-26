"""Idle timeout and sliding refresh over HTTP (ADR-0013, M20)."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import httpx
import pytest
from itsdangerous import URLSafeSerializer

from faststudio import Admin
from faststudio.auth.session import SessionManager
from tests.integration.security._accounts import AuthAdminFactory
from tests.integration.security.test_auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    LOGOUT,
    ME,
    SESSION_COOKIE,
    _login,
)

HOUR = 3600


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _with_clock(admin: Admin, clock: Clock) -> SessionManager:
    sessions: SessionManager = admin._sub_app.state.faststudio.sessions
    sessions._clock = clock
    return sessions


def _items(secret: str, value: str | None) -> list[object]:
    assert value
    data: list[object] = URLSafeSerializer(
        secret, salt="faststudio.session", signer_kwargs={"digest_method": hashlib.sha256}
    ).loads(value)
    return data


def _session_headers(response: httpx.Response) -> list[str]:
    return [
        h for h in response.headers.get_list("set-cookie") if h.startswith(f"{SESSION_COOKIE}=")
    ]


async def test_refresh_slides_the_session_once_per_window(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient, secret_key: str
) -> None:
    admin = make_auth_admin(session_idle_timeout=timedelta(hours=1))
    clock = Clock()
    _with_clock(admin, clock)
    await _login(https_client)
    first = https_client.cookies.get(SESSION_COOKIE)
    assert len(_items(secret_key, first)) == 5

    clock.now += 5 * 60 - 1
    quiet = await https_client.get(ME)
    assert quiet.status_code == 200
    assert _session_headers(quiet) == []

    clock.now += 1
    refreshed = await https_client.get(ME)
    assert refreshed.status_code == 200
    [header] = _session_headers(refreshed)
    assert refreshed.headers["cache-control"] == "no-store"
    lowered = header.lower()
    assert "httponly" in lowered
    assert "path=/admin" in lowered
    assert f"max-age={8 * HOUR - 5 * 60}" in lowered
    value = https_client.cookies.get(SESSION_COOKIE)
    old, new = _items(secret_key, first), _items(secret_key, value)
    assert new[:4] == old[:4]  # same user, auth_version, session id and issue time
    assert new[4] == int(clock.now)

    again = await https_client.get(ME)
    assert _session_headers(again) == []  # not on every request

    # Without the refresh the original cookie would be idle by now.
    clock.now += HOUR - 1
    assert (await https_client.get(ME)).status_code == 200
    # The CSRF token is still bound to the (unchanged) session id.
    token = https_client.cookies.get(CSRF_COOKIE)
    assert token
    assert (await https_client.post(LOGOUT, headers={CSRF_HEADER: token})).status_code == 204


async def test_idle_session_is_refused_and_not_refreshed(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    admin = make_auth_admin(session_idle_timeout=600)
    clock = Clock()
    _with_clock(admin, clock)
    await _login(https_client)
    clock.now += 601
    response = await https_client.get(ME)
    assert response.status_code == 401
    [header] = _session_headers(response)
    assert "max-age=0" in header.lower()


async def test_logout_is_never_overridden_by_a_refresh(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    admin = make_auth_admin(session_idle_timeout=600)
    clock = Clock()
    _with_clock(admin, clock)
    await _login(https_client)
    clock.now += 300  # a refresh is due
    token = https_client.cookies.get(CSRF_COOKIE)
    assert token
    response = await https_client.post(LOGOUT, headers={CSRF_HEADER: token})
    assert response.status_code == 204
    [header] = _session_headers(response)
    assert "max-age=0" in header.lower()
    assert (await https_client.get(ME)).status_code == 401


async def test_without_idle_timeout_nothing_slides(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient, secret_key: str
) -> None:
    admin = make_auth_admin()
    clock = Clock()
    _with_clock(admin, clock)
    await _login(https_client)
    assert len(_items(secret_key, https_client.cookies.get(SESSION_COOKIE))) == 4
    for _ in range(3):
        clock.now += 2 * HOUR
        response = await https_client.get(ME)
        assert response.status_code == 200
        assert _session_headers(response) == []
    clock.now += 2 * HOUR + 1
    assert (await https_client.get(ME)).status_code == 401


@pytest.mark.parametrize("timeout", [59, timedelta(hours=9)])
def test_admin_validates_the_idle_timeout(
    make_auth_admin: AuthAdminFactory, timeout: int | timedelta
) -> None:
    from faststudio import ConfigurationError  # noqa: PLC0415

    with pytest.raises(ConfigurationError, match="session_idle_timeout"):
        make_auth_admin(session_idle_timeout=timeout)


def test_admin_accepts_int_seconds_for_max_age(make_auth_admin: AuthAdminFactory) -> None:
    admin = make_auth_admin(session_max_age=1800, session_idle_timeout=600)
    sessions: SessionManager = admin._sub_app.state.faststudio.sessions
    assert (sessions.max_age, sessions.idle_timeout) == (1800, 600)


async def test_an_idle_write_is_401_not_a_csrf_failure(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    """The ended session is the problem, so the UI can offer to sign in again."""
    admin = make_auth_admin(session_idle_timeout=600)
    clock = Clock()
    _with_clock(admin, clock)
    await _login(https_client)
    stale = https_client.cookies.get(CSRF_COOKIE)
    assert stale
    clock.now += 601
    response = await https_client.post(LOGOUT, headers={CSRF_HEADER: stale})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    [cleared] = _session_headers(response)
    assert "max-age=0" in cleared.lower()
    fresh = https_client.cookies.get(CSRF_COOKIE)
    assert fresh
    assert fresh != stale
    assert https_client.cookies.get(SESSION_COOKIE) is None
    # The anonymous token issued with the 401 lets the admin sign in again.
    assert (await _login(https_client)).status_code == 200


async def test_a_write_without_a_valid_token_is_still_refused(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    """With a live session the token check is unchanged (403)."""
    make_auth_admin(session_idle_timeout=600)
    await _login(https_client)
    response = await https_client.post(LOGOUT, headers={CSRF_HEADER: "forged"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
