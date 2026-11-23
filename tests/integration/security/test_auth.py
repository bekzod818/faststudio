"""Login, sessions, CSRF and rate limiting over HTTP (threat model T1-T3)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from faststudio import Admin, InMemoryRateLimiter, ModelUserBackend, hash_password
from faststudio.api._paths import LOGIN_PATH
from tests.factories.models import AdminUser, Base

CSRF_COOKIE = "faststudio_csrftoken"
SESSION_COOKIE = "faststudio_session"
CSRF_HEADER = "X-FastStudio-CSRF"
LOGIN = f"/admin{LOGIN_PATH}"
LOGOUT = "/admin/api/v1/auth/logout"
ME = "/admin/api/v1/auth/me"
INVALID = {
    "error": {
        "code": "invalid_credentials",
        "message": "Invalid username or password.",
        "details": None,
    }
}


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["admin_users"]])
    maker = async_sessionmaker(engine)
    async with maker() as session:
        session.add_all(
            [
                AdminUser(username="admin", password_hash=hash_password("pw-admin"), is_admin=True),
                AdminUser(username="staff", password_hash=hash_password("pw-staff")),
                AdminUser(
                    username="gone",
                    password_hash=hash_password("pw-gone"),
                    is_admin=True,
                    is_active=False,
                ),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


AuthAdminFactory = Callable[..., Admin]


@pytest.fixture
def make_auth_admin(
    app: FastAPI,
    db_engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AuthAdminFactory:
    def factory(**options: Any) -> Admin:
        monkeypatch.setattr("faststudio.admin._STATIC_DIR", static_dir)
        return Admin(
            app,
            engine=db_engine,
            auth_backend=ModelUserBackend(AdminUser),
            secret_key=secret_key,
            **options,
        )

    return factory


@pytest.fixture
def admin(make_auth_admin: AuthAdminFactory) -> Admin:
    result: Admin = make_auth_admin()
    return result


async def _csrf(client: httpx.AsyncClient) -> str:
    """Load the SPA shell like a browser would and return the CSRF cookie value."""
    await client.get("/admin/")
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    return token


async def _login(
    client: httpx.AsyncClient, username: str = "admin", password: str = "pw-admin"
) -> httpx.Response:
    token = await _csrf(client)
    return await client.post(
        LOGIN, json={"username": username, "password": password}, headers={CSRF_HEADER: token}
    )


def _replace_cookie(client: httpx.AsyncClient, name: str, value: str) -> None:
    """Overwrite a cookie the way a browser would (same domain and path)."""
    domain, path = "testserver.local", "/admin"
    for cookie in client.cookies.jar:
        if cookie.name == name:
            domain, path = cookie.domain, cookie.path
    client.cookies.delete(name)
    client.cookies.set(name, value, domain=domain, path=path)


def _set_cookies(response: httpx.Response) -> dict[str, SimpleCookie]:
    cookies: dict[str, SimpleCookie] = {}
    for header in response.headers.get_list("set-cookie"):
        parsed = SimpleCookie()
        parsed.load(header)
        for name in parsed:
            cookies[name] = parsed
    return cookies


def _attrs(response: httpx.Response, name: str) -> str:
    header = next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))
    return header.lower()


# --------------------------------------------------------------------------- happy path


@pytest.mark.usefixtures("admin")
async def test_spa_shell_issues_csrf_cookie(https_client: httpx.AsyncClient) -> None:
    response = await https_client.get("/admin/")
    attrs = _attrs(response, CSRF_COOKIE)
    assert "secure" in attrs
    assert "samesite=lax" in attrs
    assert "path=/admin" in attrs
    assert "httponly" not in attrs  # the SPA must read it


@pytest.mark.usefixtures("admin")
async def test_login_me_logout(https_client: httpx.AsyncClient) -> None:
    anon_token = await _csrf(https_client)
    response = await https_client.post(
        LOGIN, json={"username": "admin", "password": "pw-admin"}, headers={CSRF_HEADER: anon_token}
    )
    assert response.status_code == 200
    assert response.json() == {"user": {"id": "1", "username": "admin"}}
    session_attrs = _attrs(response, SESSION_COOKIE)
    for flag in ("httponly", "secure", "samesite=lax", "path=/admin", "max-age=28800"):
        assert flag in session_attrs
    bound_token = https_client.cookies.get(CSRF_COOKIE)
    assert bound_token
    assert bound_token != anon_token  # rotated on login

    me = await https_client.get(ME)
    assert me.status_code == 200
    assert me.json() == {"user": {"id": "1", "username": "admin"}}

    out = await https_client.post(LOGOUT, headers={CSRF_HEADER: bound_token})
    assert out.status_code == 204
    assert "max-age=0" in _attrs(out, SESSION_COOKIE) or "expires=thu, 01 jan 1970" in _attrs(
        out, SESSION_COOKIE
    )
    assert https_client.cookies.get(CSRF_COOKIE) not in {None, bound_token}  # rotated again
    assert (await https_client.get(ME)).status_code == 401


# --------------------------------------------------------------------------- credentials


@pytest.mark.usefixtures("admin")
@pytest.mark.parametrize(
    ("username", "password"),
    [("admin", "wrong"), ("nobody", "pw"), ("staff", "pw-staff"), ("gone", "pw-gone")],
)
async def test_failed_logins_are_indistinguishable(
    https_client: httpx.AsyncClient, username: str, password: str
) -> None:
    response = await _login(https_client, username, password)
    assert response.status_code == 401
    assert response.json() == INVALID
    assert SESSION_COOKIE not in _set_cookies(response)


@pytest.mark.usefixtures("admin")
@pytest.mark.parametrize(
    "body",
    [
        {"username": "admin"},
        {"username": "admin", "password": "pw-admin", "is_admin": True},
        {"username": "", "password": "x"},
        {"username": "admin\nINFO forged", "password": "x"},
        {"username": "admin", "password": "SECRET-" + "x" * 2000},
    ],
)
async def test_login_body_is_validated_without_echoing_input(
    https_client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    token = await _csrf(https_client)
    response = await https_client.post(LOGIN, json=body, headers={CSRF_HEADER: token})
    assert response.status_code == 422
    assert "SECRET-" not in response.text
    assert "pw-admin" not in response.text


async def test_rate_limit(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    make_auth_admin(rate_limiter=InMemoryRateLimiter(max_attempts=3, window_seconds=60))
    for _ in range(3):
        assert (await _login(https_client, password="wrong")).status_code == 401
    blocked = await _login(https_client, password="pw-admin")  # even the right password
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0


async def test_successful_login_resets_rate_limit(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    make_auth_admin(rate_limiter=InMemoryRateLimiter(max_attempts=3, window_seconds=60))
    for _ in range(2):
        await _login(https_client, password="wrong")
    assert (await _login(https_client)).status_code == 200
    for _ in range(2):
        assert (await _login(https_client, password="wrong")).status_code == 401


async def test_rate_limit_is_per_username(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient
) -> None:
    make_auth_admin(rate_limiter=InMemoryRateLimiter(max_attempts=2, window_seconds=60))
    for _ in range(2):
        await _login(https_client, "nobody", "x")
    assert (await _login(https_client, "nobody", "x")).status_code == 429
    assert (await _login(https_client)).status_code == 200


# --------------------------------------------------------------------------- sessions


@pytest.mark.usefixtures("admin")
async def test_requests_without_session_are_rejected(https_client: httpx.AsyncClient) -> None:
    response = await https_client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.usefixtures("admin")
async def test_tampered_session_is_rejected_and_cleared(https_client: httpx.AsyncClient) -> None:
    await _login(https_client)
    value = https_client.cookies.get(SESSION_COOKIE)
    assert value
    _replace_cookie(https_client, SESSION_COOKIE, value[:-3] + "AAA")
    response = await https_client.get(ME)
    assert response.status_code == 401
    assert SESSION_COOKIE in _set_cookies(response)


async def test_expired_session_is_rejected(admin: Admin, https_client: httpx.AsyncClient) -> None:
    await _login(https_client)
    sent: list[bool] = []

    async def record(request: httpx.Request) -> None:
        sent.append(SESSION_COOKIE in request.headers.get("cookie", ""))

    https_client.event_hooks["request"].append(record)
    sessions = admin._sub_app.state.faststudio.sessions
    issued = sessions.load(https_client.cookies.get(SESSION_COOKIE)).issued_at
    sessions._clock = lambda: issued + sessions.max_age - 1
    assert (await https_client.get(ME)).status_code == 200
    sessions._clock = lambda: issued + sessions.max_age + 1
    response = await https_client.get(ME)
    assert sent == [True, True]  # the browser still sends it: the server must refuse
    assert response.status_code == 401


@pytest.mark.usefixtures("admin")
async def test_password_change_revokes_sessions(
    https_client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await _login(https_client)
    assert (await https_client.get(ME)).status_code == 200
    async with async_sessionmaker(db_engine)() as session:
        user = await session.get(AdminUser, 1)
        assert user is not None
        user.password_hash = hash_password("rotated")
        await session.commit()
    assert (await https_client.get(ME)).status_code == 401


@pytest.mark.usefixtures("admin")
@pytest.mark.parametrize("change", [{"is_active": False}, {"is_admin": False}])
async def test_deactivation_revokes_sessions(
    https_client: httpx.AsyncClient, db_engine: AsyncEngine, change: dict[str, bool]
) -> None:
    await _login(https_client)
    async with async_sessionmaker(db_engine)() as session:
        user = await session.get(AdminUser, 1)
        assert user is not None
        for key, value in change.items():
            setattr(user, key, value)
        await session.commit()
    assert (await https_client.get(ME)).status_code == 401


async def test_insecure_cookies_option(
    make_auth_admin: AuthAdminFactory, client: httpx.AsyncClient
) -> None:
    make_auth_admin(secure_cookies=False)
    response = await _login(client)
    assert response.status_code == 200
    assert "secure" not in _attrs(response, SESSION_COOKIE)
    assert (await client.get(ME)).status_code == 200


@pytest.mark.usefixtures("admin")
async def test_cookie_path_follows_proxy_prefix(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app, root_path="/proxy")
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as proxied:
        response = await proxied.get("/proxy/admin/")
        assert "path=/proxy/admin" in _attrs(response, CSRF_COOKIE)


# --------------------------------------------------------------------------- CSRF


@pytest.mark.usefixtures("admin")
@pytest.mark.parametrize("variant", ["missing", "mismatch", "forged", "cookie-only"])
async def test_login_requires_valid_csrf(https_client: httpx.AsyncClient, variant: str) -> None:
    token = await _csrf(https_client)
    headers: dict[str, str] = {}
    if variant == "mismatch":
        headers[CSRF_HEADER] = token[:-1] + ("A" if token[-1] != "A" else "B")
    elif variant == "forged":
        forged = "forgednonce.forgedmac"
        _replace_cookie(https_client, CSRF_COOKIE, forged)
        headers[CSRF_HEADER] = forged
    elif variant == "cookie-only":
        https_client.cookies.delete(CSRF_COOKIE)
        headers[CSRF_HEADER] = token
    response = await https_client.post(
        LOGIN, json={"username": "admin", "password": "pw-admin"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert SESSION_COOKIE not in _set_cookies(response)


@pytest.mark.usefixtures("admin")
async def test_anonymous_token_rejected_once_signed_in(https_client: httpx.AsyncClient) -> None:
    """Cookie tossing: an attacker-obtained anonymous token must not work for a session."""
    attacker = await _csrf(https_client)
    await _login(https_client)
    _replace_cookie(https_client, CSRF_COOKIE, attacker)
    response = await https_client.post(LOGOUT, headers={CSRF_HEADER: attacker})
    assert response.status_code == 403


@pytest.mark.usefixtures("admin")
async def test_token_from_another_session_is_rejected(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as alice,
        httpx.AsyncClient(transport=transport, base_url="https://testserver") as mallory,
    ):
        await _login(alice)
        await _login(mallory)
        mallory_token = mallory.cookies.get(CSRF_COOKIE)
        assert mallory_token
        _replace_cookie(alice, CSRF_COOKIE, mallory_token)
        response = await alice.post(LOGOUT, headers={CSRF_HEADER: mallory_token})
        assert response.status_code == 403


@pytest.mark.usefixtures("admin")
async def test_safe_methods_do_not_need_csrf(https_client: httpx.AsyncClient) -> None:
    await _login(https_client)
    assert (await https_client.get(ME)).status_code == 200


@pytest.mark.usefixtures("admin")
async def test_invalid_csrf_cookie_is_replaced(https_client: httpx.AsyncClient) -> None:
    _replace_cookie(https_client, CSRF_COOKIE, "garbage")
    await https_client.get("/admin/")
    token = https_client.cookies.get(CSRF_COOKIE)
    assert token
    assert token != "garbage"


@pytest.mark.usefixtures("admin")
async def test_valid_csrf_cookie_is_not_rotated_on_every_request(
    https_client: httpx.AsyncClient,
) -> None:
    first = await _csrf(https_client)
    response = await https_client.get("/admin/models")
    assert CSRF_COOKIE not in _set_cookies(response)
    assert https_client.cookies.get(CSRF_COOKIE) == first


# --------------------------------------------------------------------------- coverage of routes


def _all_routes(routes: list[Any]) -> list[Any]:
    """Flatten routers included with `include_router` (FastAPI may nest them)."""
    flat: list[Any] = []
    for route in routes:
        nested = getattr(route, "original_router", None)
        flat.extend(_all_routes(list(nested.routes)) if nested is not None else [route])
    return flat


async def test_every_api_route_except_login_requires_a_session(
    admin: Admin, https_client: httpx.AsyncClient
) -> None:
    token = await _csrf(https_client)
    checked = 0
    for route in _all_routes(admin._sub_app.routes):
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path == LOGIN_PATH:
            continue
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
            response = await https_client.request(
                method, f"/admin{concrete}", headers={CSRF_HEADER: token}
            )
            assert response.status_code == 401, (method, path, response.text)
            checked += 1
    assert checked >= 2  # /auth/me and /auth/logout at least


@pytest.mark.usefixtures("admin")
async def test_relogin_with_stale_anonymous_token_rotates_once(
    https_client: httpx.AsyncClient,
) -> None:
    anonymous = await _csrf(https_client)
    await _login(https_client)  # now signed in with a session-bound token
    _replace_cookie(https_client, CSRF_COOKIE, anonymous)
    response = await https_client.post(
        LOGIN,
        json={"username": "admin", "password": "pw-admin"},
        headers={CSRF_HEADER: anonymous},
    )
    assert response.status_code == 200  # login accepts an anonymous token
    csrf_cookies = [
        h for h in response.headers.get_list("set-cookie") if h.startswith(f"{CSRF_COOKIE}=")
    ]
    assert len(csrf_cookies) == 1  # the route's rotation wins; no duplicate from middleware


@pytest.mark.usefixtures("admin")
async def test_relogin_after_revocation_works(
    https_client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    await _login(https_client)
    async with async_sessionmaker(db_engine)() as session:
        user = await session.get(AdminUser, 1)
        assert user is not None
        user.password_hash = hash_password("new-password")
        await session.commit()
    rejected = await https_client.get(ME)
    assert rejected.status_code == 401
    assert CSRF_COOKIE in _set_cookies(rejected)  # fresh anonymous token issued with the 401
    token = https_client.cookies.get(CSRF_COOKIE)
    assert token
    again = await https_client.post(
        LOGIN,
        json={"username": "admin", "password": "new-password"},
        headers={CSRF_HEADER: token},
    )
    assert again.status_code == 200


@pytest.mark.usefixtures("admin")
async def test_session_cookie_path_follows_proxy_prefix(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app, root_path="/proxy")
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as proxied:
        shell = await proxied.get("/proxy/admin/")
        header = next(
            h for h in shell.headers.get_list("set-cookie") if h.startswith(f"{CSRF_COOKIE}=")
        )
        token = header.split(";", 1)[0].split("=", 1)[1]
        response = await proxied.post(
            "/proxy/admin/api/v1/auth/login",
            json={"username": "admin", "password": "pw-admin"},
            headers={CSRF_HEADER: token, "cookie": f"{CSRF_COOKIE}={token}"},
        )
        assert response.status_code == 200
        assert "path=/proxy/admin" in _attrs(response, SESSION_COOKIE)


@pytest.mark.usefixtures("admin")
async def test_assets_never_set_cookies(https_client: httpx.AsyncClient) -> None:
    response = await https_client.get("/admin/assets/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
    assert response.headers.get_list("set-cookie") == []


@pytest.mark.parametrize("variant", ["ADMIN", " admin ", "Admin", "\uff41dmin"])
async def test_rate_limit_key_is_normalized(
    make_auth_admin: AuthAdminFactory, https_client: httpx.AsyncClient, variant: str
) -> None:
    make_auth_admin(rate_limiter=InMemoryRateLimiter(max_attempts=2, window_seconds=60))
    for _ in range(2):
        await _login(https_client, "admin", "wrong")
    assert (await _login(https_client, variant, "wrong")).status_code == 429
