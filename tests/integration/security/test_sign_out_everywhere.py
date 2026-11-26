"""`POST /auth/sign-out-everywhere` with `ModelUserBackend` (ADR-0013, M20)."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Boolean, Integer, String, Text, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from faststudio import Admin, ConfigurationError, ModelAdmin, ModelUserBackend, hash_password
from faststudio.auth.capabilities import BackendCapabilities, SessionRevocation
from tests.integration.security._accounts import ORIGIN, PASSWORD

API = "/admin/api/v1"
SIGN_OUT = f"{API}/auth/sign-out-everywhere"


class _Base(DeclarativeBase):
    pass


class Staff(_Base):
    __tablename__ = "token_staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    session_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unbounded: Mapped[str | None] = mapped_column(Text, nullable=True)
    short: Mapped[str | None] = mapped_column(String(42), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        hashed = hash_password(PASSWORD)
        session.add_all(
            [
                Staff(id=1, username="ann", password_hash=hashed, session_token=None),
                Staff(id=2, username="bob", password_hash=hashed, session_token=""),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


def _mount(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    **options: Any,
) -> Admin:
    monkeypatch.setattr("faststudio.admin._STATIC_DIR", static_dir)
    return Admin(
        app, engine=engine, auth_backend=ModelUserBackend(Staff, **options), secret_key=secret_key
    )


async def _client(stack: AsyncExitStack, app: FastAPI, username: str) -> httpx.AsyncClient:
    http = await stack.enter_async_context(
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
    )
    await http.get(f"{API}/auth/me")
    response = await http.post(
        f"{API}/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    return http


def _headers(http: httpx.AsyncClient) -> dict[str, str]:
    return {"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN}


async def _token(engine: AsyncEngine, pk: int) -> str | None:
    async with AsyncSession(engine) as session:
        return (await session.execute(select(Staff.session_token).where(Staff.id == pk))).scalar()


async def test_with_a_token_column_every_session_ends(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mount(app, engine, secret_key, static_dir, monkeypatch, session_token_field="session_token")
    # NULL and empty tokens still sign in (they count as "").
    async with AsyncExitStack() as stack:
        here = await _client(stack, app, "ann")
        elsewhere = await _client(stack, app, "ann")
        other = await _client(stack, app, "bob")
        meta = (await here.get(f"{API}/meta")).json()
        assert meta["capabilities"]["sign_out_everywhere"] is True
        response = await here.post(SIGN_OUT, headers=_headers(here))
        assert response.status_code == 204
        assert (await here.get(f"{API}/auth/me")).status_code == 401
        assert (await elsewhere.get(f"{API}/auth/me")).status_code == 401
        assert (await other.get(f"{API}/auth/me")).status_code == 200
    token = await _token(engine, 1)
    assert token is not None
    assert len(token) >= 43  # the first rotation sets a value
    assert await _token(engine, 2) == ""


async def test_password_changes_leave_the_token_alone(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _mount(
        app,
        engine,
        secret_key,
        static_dir,
        monkeypatch,
        session_token_field="session_token",
        password_endpoints=True,
    )
    async with AsyncSession(engine) as session:
        await session.execute(update(Staff).where(Staff.id == 1).values(session_token="t" * 43))
        await session.commit()
    async with AsyncExitStack() as stack:
        http = await _client(stack, app, "ann")
        response = await http.post(
            f"{API}/auth/password",
            json={"current_password": PASSWORD, "new_password": "a different passphrase"},
            headers=_headers(http),
        )
        assert response.status_code == 204, response.text
    accounts: Any = admin._capabilities.accounts
    async with AsyncSession(engine) as session:
        await accounts.set_password(session, "1", "yet another passphrase")
        await session.commit()
    assert await _token(engine, 1) == "t" * 43


async def test_createadmin_sets_a_fresh_token(engine: AsyncEngine) -> None:
    backend = ModelUserBackend(Staff, session_token_field="session_token")
    accounts: Any = backend.faststudio_capabilities.accounts
    assert "session_token" not in accounts.required_fields()
    async with AsyncSession(engine) as session:
        account_id = await accounts.create_admin(
            session, username="cat", password=PASSWORD, fields={}
        )
        await session.commit()
    token = await _token(engine, int(account_id))
    assert token is not None
    assert len(token) >= 43
    with pytest.raises(ValueError, match="session_token"):
        async with AsyncSession(engine) as session:
            await accounts.create_admin(
                session, username="dan", password=PASSWORD, fields={"session_token": "x"}
            )


async def test_without_the_capability_the_endpoint_is_404(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _mount(app, engine, secret_key, static_dir, monkeypatch)
    assert admin._capabilities.session_revocation is None
    async with AsyncExitStack() as stack:
        http = await _client(stack, app, "ann")
        meta = (await http.get(f"{API}/meta")).json()
        assert meta["capabilities"]["sign_out_everywhere"] is False
        response = await http.post(SIGN_OUT, headers=_headers(http))
        assert response.status_code == 404
        assert (await http.get(f"{API}/auth/me")).status_code == 200


async def test_a_session_is_required(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mount(app, engine, secret_key, static_dir, monkeypatch, session_token_field="session_token")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:
        await http.get(f"{API}/auth/me")
        assert (await http.post(SIGN_OUT, headers=_headers(http))).status_code == 401


async def test_a_deleted_account_gets_401(engine: AsyncEngine) -> None:
    backend = ModelUserBackend(Staff, session_token_field="session_token")
    revocation = backend.faststudio_capabilities.session_revocation
    assert isinstance(revocation, SessionRevocation)
    async with AsyncSession(engine) as session:
        for missing in ("99", "not-a-pk"):
            with pytest.raises(LookupError):
                await revocation.rotate_session_token(session, missing)


def test_the_token_column_is_a_secret_field(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _mount(
        app, engine, secret_key, static_dir, monkeypatch, session_token_field="unbounded"
    )

    class Leaky(ModelAdmin, model=Staff):
        exclude = ("password_hash",)

    with pytest.raises(ConfigurationError, match="unbounded"):
        admin.register(Leaky)

    class Careful(ModelAdmin, model=Staff):
        exclude = ("password_hash", "unbounded")

    admin.register(Careful)


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("missing", "is not a column"),
        ("short", "at least 43 characters"),
        ("count", "at least 43 characters"),
        ("id", "primary key"),
        ("password_hash", "a column of its own"),
        ("username", "a column of its own"),
        ("is_active", "a column of its own"),
        ("email", "a column of its own"),
    ],
)
def test_invalid_token_columns_are_refused(field: str, match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        ModelUserBackend(Staff, session_token_field=field)


def test_the_v0_1_auth_version_is_unchanged_without_the_option() -> None:
    row = Staff(id=1, username="ann", password_hash="h", is_active=True, is_admin=True)
    plain = ModelUserBackend(Staff)
    with_token = ModelUserBackend(Staff, session_token_field="session_token")
    # v0.1: sha256("hash|is_active|is_admin")[:32]
    import hashlib  # noqa: PLC0415

    assert plain._user(row).auth_version == hashlib.sha256(b"h|True|True").hexdigest()[:32]
    assert with_token._user(row).auth_version == hashlib.sha256(b"h|True|True|").hexdigest()[:32]
    assert plain.faststudio_capabilities.session_revocation is None


class _Vanished:
    async def rotate_session_token(self, session: AsyncSession, account_id: str) -> None:
        del session
        raise LookupError(account_id)


async def test_an_account_deleted_meanwhile_gets_401(
    app: FastAPI,
    engine: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Backend(ModelUserBackend):
        @property
        def faststudio_capabilities(self) -> BackendCapabilities:
            capabilities = super().faststudio_capabilities
            return dataclasses.replace(capabilities, session_revocation=_Vanished())

    monkeypatch.setattr("faststudio.admin._STATIC_DIR", static_dir)
    Admin(app, engine=engine, auth_backend=Backend(Staff), secret_key=secret_key)
    async with AsyncExitStack() as stack:
        http = await _client(stack, app, "ann")
        response = await http.post(SIGN_OUT, headers=_headers(http))
        assert response.status_code == 401
        cookies = response.headers.get_list("set-cookie")
        assert any(c.startswith("faststudio_session=") and "Max-Age=0" in c for c in cookies)
        assert any(c.startswith("faststudio_csrftoken=") for c in cookies)
