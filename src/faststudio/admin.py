"""The :class:`Admin` entry point."""

from __future__ import annotations

import inspect
from datetime import timedelta
from typing import TypeVar, cast

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from faststudio.auth.backend import AuthBackend
from faststudio.config import Settings, resolve_settings
from faststudio.exceptions import ConfigurationError

_T = TypeVar("_T")


class Admin:
    """A FastStudio admin site attached to a FastAPI application.

    All options are validated eagerly; misconfiguration raises
    :class:`~faststudio.ConfigurationError` at startup rather than at request
    time. (Mounting the UI and API under ``base_url`` arrives in a later
    milestone.)
    """

    def __init__(
        self,
        app: FastAPI,
        *,
        engine: AsyncEngine | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        auth_backend: AuthBackend,
        secret_key: str | None = None,
        title: str = "FastStudio",
        base_url: str = "/admin",
        session_max_age: timedelta = timedelta(hours=8),
        secure_cookies: bool = True,
        max_page_size: int = 100,
        show_powered_by: bool = True,
    ) -> None:
        """Configure FastStudio for ``app``.

        Args:
            app: The host FastAPI application.
            engine: An ``AsyncEngine``; FastStudio creates its own session factory.
            session_maker: Alternatively, your own ``async_sessionmaker``.
                Exactly one of ``engine`` and ``session_maker`` is required.
            auth_backend: Authenticates admins, e.g. ``ModelUserBackend(User)``.
            secret_key: Signs sessions and CSRF tokens. Defaults to the
                ``FASTSTUDIO_SECRET_KEY`` environment variable. Must be at least
                32 random characters.
            title: Title shown in the UI.
            base_url: Mount path, e.g. ``/admin``.
            session_max_age: Absolute session lifetime.
            secure_cookies: Set the ``Secure`` cookie flag. Disable only for
                plain-HTTP development on non-localhost hosts.
            max_page_size: Upper bound for list page sizes.
            show_powered_by: Show the "Powered by FastStudio" footer.

        Raises:
            ConfigurationError: if any option is invalid.

        """
        self._app = _require_instance(
            app, FastAPI, f"app must be a FastAPI instance, got {type(app).__name__}."
        )
        self._session_maker = _resolve_session_maker(engine, session_maker)
        self._auth_backend = _validate_auth_backend(auth_backend)
        self._settings: Settings = resolve_settings(
            secret_key=secret_key,
            title=title,
            base_url=base_url,
            session_max_age=session_max_age,
            secure_cookies=secure_cookies,
            max_page_size=max_page_size,
            show_powered_by=show_powered_by,
        )

    @property
    def base_url(self) -> str:
        """Normalized mount path, without a trailing slash."""
        return self._settings.base_url

    @property
    def title(self) -> str:
        """Title shown in the UI."""
        return self._settings.title


def _require_instance(value: object, cls: type[_T], msg: str) -> _T:
    """Runtime type guard: static types are bypassed by untyped callers."""
    if not isinstance(value, cls):
        raise ConfigurationError(msg)
    return value


def _validate_auth_backend(backend: AuthBackend) -> AuthBackend:
    msg = (
        "auth_backend must be an instance implementing the AuthBackend protocol with "
        "async authenticate() and get_user() methods, e.g. ModelUserBackend(User)."
    )
    candidate = cast("object", backend)
    if isinstance(candidate, type) or not isinstance(candidate, AuthBackend):
        raise ConfigurationError(msg)
    if not all(
        inspect.iscoroutinefunction(getattr(backend, name)) for name in ("authenticate", "get_user")
    ):
        raise ConfigurationError(msg)
    return backend


def _resolve_session_maker(
    engine: AsyncEngine | None,
    session_maker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    if (engine is None) == (session_maker is None):
        msg = "Pass exactly one of engine= or session_maker= to Admin()."
        raise ConfigurationError(msg)
    if session_maker is not None:
        maker: async_sessionmaker[AsyncSession] = _require_instance(
            session_maker,
            async_sessionmaker,
            "session_maker must be an sqlalchemy.ext.asyncio.async_sessionmaker.",
        )
        return maker
    async_engine = _require_instance(
        engine,
        AsyncEngine,
        "engine must be an sqlalchemy AsyncEngine (use create_async_engine() with an "
        "async driver such as aiosqlite or asyncpg).",
    )
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
