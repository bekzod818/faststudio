"""Password endpoints (ADR-0013; threat model T2; M18a)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from faststudio import Admin, InMemoryRateLimiter, ModelAdmin, ModelUserBackend, hash_password
from tests.factories.auth_models import AuthBase, AuthPermission, AuthUser, PermBackend
from tests.factories.models import AdminUser, Base, Team

ORIGIN = "https://testserver"
API = "/admin/api/v1"
OLD = "the old passphrase 1"
NEW = "a brand new passphrase"


class AdminUserAdmin(ModelAdmin, model=AdminUser):
    list_display = ("id", "username")
    exclude = ("password_hash",)


class TeamAdmin(ModelAdmin, model=Team):
    list_display = ("id", "name")


class Client:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def post(self, path: str, body: object, *, csrf: bool = True) -> httpx.Response:
        headers = self.headers() if csrf else {"origin": ORIGIN}
        return await self.http.post(f"{API}{path}", json=body, headers=headers)

    async def me(self) -> int:
        return (await self.http.get(f"{API}/auth/me")).status_code


SignIn = Callable[..., Awaitable[Client]]


async def _open(stack: AsyncExitStack, app: FastAPI) -> httpx.AsyncClient:
    return await stack.enter_async_context(
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
    )


async def _login(http: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
    await http.get(f"{API}/auth/me")
    return await http.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        headers={"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN},
    )


# --------------------------------------------------------------------------- ModelUserBackend


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/passwords.db")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables["admin_users"], Base.metadata.tables["teams"]],
        )
        await conn.run_sync(AuthBase.metadata.create_all)
    hashed = hash_password(OLD)
    async with AsyncSession(engine) as session:
        session.add_all(
            AdminUser(id=i, username=name, password_hash=hashed, is_active=True, is_admin=True)
            for i, name in [(1, "alice"), (2, "bob")]
        )
        session.add_all(
            [
                AuthUser(id=1, username="root", password_hash=hashed, is_superuser=True),
                AuthUser(id=2, username="manager", password_hash=hashed),
                AuthUser(id=3, username="carol", password_hash=hashed),
                AuthPermission(id=1, codename="t_users.edit"),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


@pytest.fixture
def endpoints() -> bool:
    return True


@pytest.fixture
def admin(app: FastAPI, db: AsyncEngine, secret_key: str, endpoints: bool) -> Admin:
    instance = Admin(
        app,
        engine=db,
        auth_backend=ModelUserBackend(AdminUser, password_endpoints=endpoints),
        secret_key=secret_key,
        rate_limiter=InMemoryRateLimiter(max_attempts=3, window_seconds=60),
    )
    instance.register(AdminUserAdmin)
    instance.register(TeamAdmin)
    return instance


@pytest.fixture
async def sign_in(app: FastAPI, admin: Admin) -> AsyncIterator[SignIn]:
    del admin
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str = "alice", password: str = OLD) -> Client:
            http = await _open(stack, app)
            response = await _login(http, username, password)
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


@pytest.mark.parametrize("endpoints", [False])
async def test_endpoints_are_off_by_default_for_model_user_backend(sign_in: SignIn) -> None:
    alice = await sign_in()
    meta = (await alice.http.get(f"{API}/meta")).json()
    assert meta["capabilities"] == {"change_password": False, "sign_out_everywhere": False}
    users = next(m for m in meta["models"] if m["identity"] == "admin_users")
    assert users["account"]["set_password"] is False
    body = {"current_password": OLD, "new_password": NEW}
    assert (await alice.post("/auth/password", body)).status_code == 404
    assert (
        await alice.post("/models/admin_users/items/2/password", {"new_password": NEW})
    ).status_code == 404


async def test_meta_advertises_the_endpoints(sign_in: SignIn) -> None:
    meta = (await (await sign_in()).http.get(f"{API}/meta")).json()
    assert meta["capabilities"] == {"change_password": True, "sign_out_everywhere": False}
    accounts = {m["identity"]: m["account"] for m in meta["models"]}
    assert accounts["admin_users"]["set_password"] is True
    assert accounts["teams"] is None


async def test_change_password_revokes_other_sessions(sign_in: SignIn) -> None:
    other_device = await sign_in()
    alice = await sign_in()
    response = await alice.post("/auth/password", {"current_password": OLD, "new_password": NEW})
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await other_device.me() == 401  # the hash is part of auth_version
    assert await alice.me() == 200  # re-issued session, and a CSRF token bound to it
    assert (await alice.http.post(f"{API}/auth/logout", headers=alice.headers())).status_code == 204
    assert (await sign_in("alice", NEW)).http.cookies.get("faststudio_session")


@pytest.mark.parametrize(
    ("body", "loc", "messages"),
    [
        (
            {"current_password": "wrong but long enough", "new_password": NEW},
            "current_password",
            ["The current password is incorrect."],
        ),
        (
            {"current_password": OLD, "new_password": "short"},
            "new_password",
            ["Use at least 12 characters."],
        ),
        (
            {"current_password": OLD, "new_password": "alice-is-the-admin"},
            "new_password",
            ["Make the password less similar to the account's name or email."],
        ),
        (
            {"current_password": OLD, "new_password": OLD},
            "new_password",
            ["Choose a password you have not used here."],
        ),
    ],
)
async def test_refused_changes_leave_the_password_alone(
    sign_in: SignIn, body: dict[str, str], loc: str, messages: list[str]
) -> None:
    alice = await sign_in()
    response = await alice.post("/auth/password", body)
    assert response.status_code == 422, response.text
    details = response.json()["error"]["details"]
    assert [(d["loc"], d["msg"]) for d in details] == [([loc], m) for m in messages]
    assert await alice.me() == 200
    await sign_in("alice", OLD)  # unchanged


async def test_wrong_current_passwords_are_rate_limited(sign_in: SignIn) -> None:
    alice = await sign_in()
    wrong = {"current_password": "not the password", "new_password": NEW}
    statuses = [(await alice.post("/auth/password", wrong)).status_code for _ in range(4)]
    assert statuses == [422, 422, 422, 429]
    limited = await alice.post("/auth/password", {"current_password": OLD, "new_password": NEW})
    assert limited.status_code == 429  # even the right password, until the window passes
    assert int(limited.headers["retry-after"]) > 0


async def test_password_changes_need_csrf(sign_in: SignIn) -> None:
    alice = await sign_in()
    body = {"current_password": OLD, "new_password": NEW}
    response = await alice.post("/auth/password", body, csrf=False)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


@pytest.mark.parametrize(
    "body",
    [
        {"current_password": OLD},
        {"current_password": OLD, "new_password": NEW, "extra": 1},
        {"current_password": OLD, "new_password": "x" * 1025},
    ],
)
async def test_bodies_are_strict_and_never_echoed(sign_in: SignIn, body: dict[str, Any]) -> None:
    alice = await sign_in()
    response = await alice.post("/auth/password", body)
    assert response.status_code == 422
    assert OLD not in response.text
    assert "x" * 100 not in response.text


async def test_set_password_of_another_admin(sign_in: SignIn) -> None:
    bob_before = await sign_in("bob")
    alice = await sign_in()
    response = await alice.post("/models/admin_users/items/2/password", {"new_password": NEW})
    assert response.status_code == 204, response.text
    assert await bob_before.me() == 401  # bob's sessions are revoked
    await sign_in("bob", NEW)


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        ("/models/admin_users/items/1/password", {"new_password": NEW}, 403),  # own account
        ("/models/admin_users/items/99/password", {"new_password": NEW}, 404),
        ("/models/teams/items/1/password", {"new_password": NEW}, 404),  # not an account model
        ("/models/admin_users/items/2/password", {"new_password": "bob-the-builder"}, 422),
    ],
)
async def test_set_password_refusals(
    sign_in: SignIn, path: str, body: dict[str, str], status: int
) -> None:
    alice = await sign_in()
    response = await alice.post(path, body)
    assert response.status_code == status, response.text
    await sign_in("bob", OLD)  # unchanged


async def test_passwords_never_reach_logs(
    sign_in: SignIn, caplog: pytest.LogCaptureFixture
) -> None:
    alice = await sign_in()
    with caplog.at_level("DEBUG"):
        await alice.post(
            "/auth/password", {"current_password": "secret guess 42", "new_password": NEW}
        )
        await alice.post("/auth/password", {"current_password": OLD, "new_password": "short"})
        await alice.post("/models/admin_users/items/2/password", {"new_password": NEW})
    for secret in ("secret guess 42", NEW, OLD, "short"):
        assert secret not in caplog.text


# --------------------------------------------------------------------------- permission backend


class AuthUserAdmin(ModelAdmin, model=AuthUser):
    identity = "t_users"
    list_display = ("id", "username")
    exclude = ("password_hash",)


@pytest.fixture
async def perm_sign_in(app: FastAPI, db: AsyncEngine, secret_key: str) -> AsyncIterator[SignIn]:
    from sqlalchemy import insert  # noqa: PLC0415

    from tests.factories.auth_models import user_permissions  # noqa: PLC0415

    async with db.begin() as conn:
        await conn.execute(insert(user_permissions), [{"user_id": 2, "permission_id": 1}])
    instance = Admin(
        app, engine=db, auth_backend=PermBackend(password_endpoints=True), secret_key=secret_key
    )
    instance.register(AuthUserAdmin)
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str, password: str = OLD) -> Client:
            http = await _open(stack, app)
            response = await _login(http, username, password)
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


async def test_setting_passwords_needs_every_permission(perm_sign_in: SignIn) -> None:
    manager = await perm_sign_in("manager")
    meta = (await manager.http.get(f"{API}/meta")).json()
    assert meta["models"][0]["account"]["set_password"] is False
    assert meta["capabilities"]["change_password"] is True
    refused = await manager.post("/models/t_users/items/3/password", {"new_password": NEW})
    assert refused.status_code == 403  # before the record is loaded: no existence oracle
    assert (
        await manager.post("/models/t_users/items/99/password", {"new_password": NEW})
    ).status_code == 403
    own = await manager.post("/auth/password", {"current_password": OLD, "new_password": NEW})
    assert own.status_code == 204  # anyone may change their own
    root = await perm_sign_in("root")
    assert (
        await root.post("/models/t_users/items/3/password", {"new_password": NEW})
    ).status_code == 204
    await perm_sign_in("carol", NEW)


# --------------------------------------------------------------------------- races and limits


def _accounts(admin: Admin) -> Any:
    return admin._capabilities.accounts


async def test_the_per_client_limiter_also_applies(
    sign_in: SignIn, admin: Admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    from faststudio import RateLimitDecision  # noqa: PLC0415

    alice = await sign_in()

    async def exhausted(key: str) -> RateLimitDecision:
        del key
        return RateLimitDecision(allowed=False, retry_after=30)

    monkeypatch.setattr(admin._sub_app.state.faststudio.client_rate_limiter, "hit", exhausted)
    response = await alice.post("/auth/password", {"current_password": OLD, "new_password": NEW})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"


@pytest.mark.parametrize("path", ["/auth/password", "/models/admin_users/items/2/password"])
async def test_an_account_deleted_meanwhile_is_404(
    sign_in: SignIn, admin: Admin, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    alice = await sign_in()

    async def gone(session: object, account_id: str, password: str) -> None:
        del session, password
        raise LookupError(account_id)

    monkeypatch.setattr(_accounts(admin), "set_password", gone)
    body: dict[str, str] = {"new_password": NEW}
    if path == "/auth/password":
        body["current_password"] = OLD
    assert (await alice.post(path, body)).status_code == 404


async def test_an_account_deactivated_meanwhile_is_signed_out(
    sign_in: SignIn, admin: Admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await sign_in()
    backend = admin._auth_backend
    original = backend.get_user
    calls = {"n": 0}

    async def deactivated_after_the_change(request: Any, user_id: str) -> Any:
        calls["n"] += 1
        return None if calls["n"] > 1 else await original(request, user_id)

    monkeypatch.setattr(backend, "get_user", deactivated_after_the_change)
    response = await alice.post("/auth/password", {"current_password": OLD, "new_password": NEW})
    assert response.status_code == 401


async def test_set_password_follows_the_edit_hooks(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    """Setting a password is an edit: can_edit and object-level hooks apply."""
    from starlette.requests import Request  # noqa: PLC0415

    class LockedAdmin(ModelAdmin, model=AdminUser):
        list_display = ("id", "username")
        exclude = ("password_hash",)

        @classmethod
        async def has_edit_permission(cls, request: Request, obj: object | None = None) -> bool:
            if isinstance(obj, AdminUser) and obj.username == "bob":
                return False  # a break-glass account
            return await super().has_edit_permission(request, obj)

    class HiddenAdmin(ModelAdmin, model=AdminUser):
        list_display = ("id", "username")
        exclude = ("password_hash",)
        can_edit = False

    class InvisibleAdmin(ModelAdmin, model=AdminUser):
        list_display = ("id", "username")
        exclude = ("password_hash",)

        @classmethod
        async def has_view_permission(cls, request: Request, obj: object | None = None) -> bool:
            if isinstance(obj, AdminUser) and obj.username == "bob":
                return False  # hidden from retrieve: hidden here too
            return await super().has_view_permission(request, obj)

    cases = ((LockedAdmin, 403), (HiddenAdmin, 403), (InvisibleAdmin, 404))
    for admin_class, expected in cases:  # object-level edit, model-level edit, object view
        sub = FastAPI()
        instance = Admin(
            sub,
            engine=db,
            auth_backend=ModelUserBackend(AdminUser, password_endpoints=True),
            secret_key=secret_key,
        )
        instance.register(admin_class)
        async with AsyncExitStack() as stack:
            http = await _open(stack, sub)
            assert (await _login(http, "alice", OLD)).status_code == 200
            alice = Client(http)
            response = await alice.post(
                "/models/admin_users/items/2/password", {"new_password": NEW}
            )
            assert response.status_code == expected, (admin_class.__name__, response.text)
            meta = (await http.get(f"{API}/meta")).json()
            assert meta["models"][0]["account"]["set_password"] is (admin_class is not HiddenAdmin)
    del app
