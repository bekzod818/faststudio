import secrets
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from faststudio import Admin, ConfigurationError
from tests._stubs import StubAuthBackend, SyncAuthBackend


def test_admin_with_engine(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    admin = Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)
    assert admin.base_url == "/admin"
    assert admin.title == "FastStudio"
    assert admin._session_maker.kw["bind"] is engine
    assert admin._session_maker.kw["expire_on_commit"] is False


def test_admin_with_session_maker(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    maker = async_sessionmaker(engine, class_=AsyncSession)
    admin = Admin(app, session_maker=maker, auth_backend=auth_backend, secret_key=secret_key)
    assert admin._session_maker is maker


def test_admin_reads_secret_from_env(
    app: FastAPI,
    engine: AsyncEngine,
    auth_backend: StubAuthBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FASTSTUDIO_SECRET_KEY", secrets.token_urlsafe(48))
    Admin(app, engine=engine, auth_backend=auth_backend)


def test_admin_without_secret_fails_loudly(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend
) -> None:
    with pytest.raises(ConfigurationError, match="FASTSTUDIO_SECRET_KEY"):
        Admin(app, engine=engine, auth_backend=auth_backend)


def test_admin_with_weak_secret_fails(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend
) -> None:
    with pytest.raises(ConfigurationError, match="at least 32"):
        Admin(app, engine=engine, auth_backend=auth_backend, secret_key="changeme")


def test_admin_custom_options(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    admin = Admin(
        app,
        engine=engine,
        auth_backend=auth_backend,
        secret_key=secret_key,
        title="Back Office",
        base_url="/studio/",
    )
    assert admin.base_url == "/studio"
    assert admin.title == "Back Office"


def test_requires_engine_or_session_maker(
    app: FastAPI, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    with pytest.raises(ConfigurationError, match="exactly one of"):
        Admin(app, auth_backend=auth_backend, secret_key=secret_key)


def test_rejects_both_engine_and_session_maker(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    with pytest.raises(ConfigurationError, match="exactly one of"):
        Admin(
            app,
            engine=engine,
            session_maker=async_sessionmaker(engine),
            auth_backend=auth_backend,
            secret_key=secret_key,
        )


def test_rejects_sync_engine(app: FastAPI, auth_backend: StubAuthBackend, secret_key: str) -> None:
    sync_engine = create_engine("sqlite://")
    try:
        with pytest.raises(ConfigurationError, match="AsyncEngine"):
            Admin(app, engine=sync_engine, auth_backend=auth_backend, secret_key=secret_key)  # type: ignore[arg-type]  # deliberately wrong type
    finally:
        sync_engine.dispose()


def test_rejects_non_async_session_maker(
    app: FastAPI, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    with pytest.raises(ConfigurationError, match="async_sessionmaker"):
        Admin(app, session_maker=object(), auth_backend=auth_backend, secret_key=secret_key)  # type: ignore[arg-type]  # deliberately wrong type


@pytest.mark.parametrize(
    "backend",
    [None, object(), "backend", StubAuthBackend, SyncAuthBackend()],
    ids=["none", "object", "str", "class-not-instance", "sync-methods"],
)
def test_rejects_invalid_auth_backend(
    app: FastAPI, engine: AsyncEngine, secret_key: str, backend: Any
) -> None:
    with pytest.raises(ConfigurationError, match="AuthBackend"):
        Admin(app, engine=engine, auth_backend=backend, secret_key=secret_key)


def test_rejects_invalid_app(
    engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    with pytest.raises(ConfigurationError, match="FastAPI"):
        Admin(object(), engine=engine, auth_backend=auth_backend, secret_key=secret_key)  # type: ignore[arg-type]  # deliberately wrong type


def test_invalid_base_url_propagates(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    with pytest.raises(ConfigurationError, match="base_url"):
        Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key, base_url="/")
