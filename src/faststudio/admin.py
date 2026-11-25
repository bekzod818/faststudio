"""The :class:`Admin` entry point."""

from __future__ import annotations

import inspect
from datetime import timedelta
from pathlib import Path
from typing import TypeVar, cast

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from faststudio.api._app import create_admin_app, wrap_admin_app
from faststudio.api._context import AdminContext
from faststudio.api._escalation import EscalationRules
from faststudio.auth.backend import AuthBackend
from faststudio.auth.capabilities import BackendCapabilities, PermissionBackend
from faststudio.auth.csrf import CsrfTokens
from faststudio.auth.guard import AccountGuard
from faststudio.auth.session import SessionManager
from faststudio.config import DEFAULT_MAX_LIST_OFFSET, Settings, resolve_settings
from faststudio.exceptions import ConfigurationError
from faststudio.model_admin import ModelAdmin
from faststudio.registry import Registry, resolve_model_admin
from faststudio.security.headers import SecurityHeadersMiddleware
from faststudio.security.rate_limit import (
    CLIENT_MAX_ATTEMPTS,
    CLIENT_WINDOW_SECONDS,
    InMemoryRateLimiter,
    RateLimiter,
)

_T = TypeVar("_T")
_A = TypeVar("_A", bound=type[ModelAdmin])
_STATIC_DIR = Path(__file__).resolve().parent / "static"


class Admin:
    """A FastStudio admin site attached to a FastAPI application.

    All options are validated eagerly; misconfiguration raises
    :class:`~faststudio.ConfigurationError` at startup rather than at request
    time. The admin is mounted on ``app`` at ``base_url`` as an isolated
    sub-application (its own error handling and security headers; nothing is
    added to the host's OpenAPI schema).
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
        max_list_offset: int = DEFAULT_MAX_LIST_OFFSET,
        rate_limiter: RateLimiter | None = None,
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
            max_list_offset: Lists and relation choices never skip this many
                rows or more: a page is reachable only while
                ``(page - 1) * page_size < max_list_offset``. Deep ``OFFSET``s
                scan every skipped row; raise it only if your database can
                afford that, otherwise narrow results with search, filters or
                sorting. 1 to 10 000 000.
            rate_limiter: Login throttling; defaults to `InMemoryRateLimiter()`
                (5 attempts per 15 minutes per client IP and username, per process).
            show_powered_by: Show the "Powered by FastStudio" footer.

        Raises:
            ConfigurationError: if any option is invalid.

        """
        self._app = _require_instance(
            app, FastAPI, f"app must be a FastAPI instance, got {type(app).__name__}."
        )
        self._session_maker = _resolve_session_maker(engine, session_maker)
        self._auth_backend = _validate_auth_backend(auth_backend)
        self._capabilities = _resolve_capabilities(self._auth_backend)
        self._escalation = EscalationRules.from_capabilities(self._capabilities)
        self._settings: Settings = resolve_settings(
            secret_key=secret_key,
            title=title,
            base_url=base_url,
            session_max_age=session_max_age,
            secure_cookies=secure_cookies,
            max_page_size=max_page_size,
            max_list_offset=max_list_offset,
            show_powered_by=show_powered_by,
        )

        self._registry = Registry()
        context = AdminContext(
            settings=self._settings,
            registry=self._registry,
            session_maker=self._session_maker,
            auth_backend=self._auth_backend,
            capabilities=self._capabilities,
            escalation=self._escalation,
            static_dir=_STATIC_DIR,
            sessions=SessionManager(
                self._settings.secret_key,
                max_age=int(self._settings.session_max_age.total_seconds()),
            ),
            csrf=CsrfTokens(self._settings.secret_key),
            rate_limiter=_validate_rate_limiter(rate_limiter),
            client_rate_limiter=InMemoryRateLimiter(
                max_attempts=CLIENT_MAX_ATTEMPTS, window_seconds=CLIENT_WINDOW_SECONDS
            ),
        )
        self._sub_app = create_admin_app(context)
        base_url = self._settings.base_url
        app.router.routes.append(
            Route(
                base_url,
                SecurityHeadersMiddleware(_TrailingSlashRedirect()),
                include_in_schema=False,
            )
        )
        app.mount(base_url, wrap_admin_app(self._sub_app, context), name="faststudio")

    def register(self, model_admin: _A) -> _A:
        """Validate and register a :class:`ModelAdmin` subclass.

        Usable as a class decorator. Returns the class unchanged.

        Raises:
            ConfigurationError: on unknown or misspelled options, unknown field
                names, search/filter fields of unsupported types, excluded fields
                used elsewhere, composite primary keys, a duplicate identity or
                model, or another mapping of the auth backend's user table,
                including sibling subclasses sharing that table (only the user
                model or a subclass is allowed; ADR-0009).

        """
        registered = resolve_model_admin(model_admin, max_page_size=self._settings.max_page_size)
        guard = self._capabilities.account_guard
        if guard is not None:
            guard.check_model(registered.model)
        if self._escalation is not None:
            self._escalation.check_model(registered)
        self._registry.add(registered)
        return model_admin

    @property
    def base_url(self) -> str:
        """Normalized mount path, without a trailing slash."""
        return self._settings.base_url

    @property
    def title(self) -> str:
        """Title shown in the UI."""
        return self._settings.title


class _TrailingSlashRedirect:
    """Redirect `{base_url}` to `{base_url}/`, keeping the query string."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Per the ASGI spec `path` already includes any proxy `root_path`.
        target = f"{scope['path']}/"
        if scope.get("query_string"):
            target += "?" + scope["query_string"].decode("latin-1")
        await RedirectResponse(target, status_code=307)(scope, receive, send)


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


#: 0.1.1's private guard protocol (ADR-0009); now `BackendCapabilities.account_guard`.
_LEGACY_GUARD_METHODS = ("guards", "before_write", "check_model")


def _resolve_capabilities(backend: AuthBackend) -> BackendCapabilities:
    """Validate the backend's optional `faststudio_capabilities` (ADR-0011 §1).

    Nothing else on the backend is inspected, except that a backend which still
    implements 0.1.1's private guard methods must migrate: silently ignoring
    them would drop its account guard (fail open).
    """
    capabilities: object = getattr(backend, "faststudio_capabilities", None)
    if capabilities is None:
        if all(callable(getattr(backend, name, None)) for name in _LEGACY_GUARD_METHODS):
            msg = (
                f"{type(backend).__name__} implements the 0.1.1 account guard methods "
                "(guards, before_write, check_model) but no faststudio_capabilities. "
                "Return BackendCapabilities(account_guard=...) from a "
                "faststudio_capabilities property; see FlagAccountGuard (ADR-0011)."
            )
            raise ConfigurationError(msg)
        return BackendCapabilities()
    if not isinstance(capabilities, BackendCapabilities):
        msg = "faststudio_capabilities must be a faststudio.BackendCapabilities instance."
        raise ConfigurationError(msg)
    _check_protocol(
        capabilities.account_guard,
        AccountGuard,
        "account_guard",
        sync=("guards", "check_model", "protected_fields", "admin_flag", "permission_schema"),
        coroutines=("before_write",),
    )
    _check_protocol(
        capabilities.permissions,
        PermissionBackend,
        "permissions",
        sync=(),
        coroutines=("resolve", "resolve_accounts"),
    )
    return capabilities


def _check_protocol(
    value: object,
    protocol: type,
    name: str,
    *,
    sync: tuple[str, ...],
    coroutines: tuple[str, ...],
) -> None:
    if value is None:
        return
    ok = (
        not isinstance(value, type)
        and isinstance(value, protocol)
        and all(callable(getattr(value, method)) for method in sync)
        and all(inspect.iscoroutinefunction(getattr(value, method)) for method in coroutines)
    )
    if not ok:
        methods = ", ".join([*sync, *(f"async {m}" for m in coroutines)])
        msg = f"BackendCapabilities.{name} must implement {protocol.__name__} ({methods})."
        raise ConfigurationError(msg)


def _validate_rate_limiter(limiter: RateLimiter | None) -> RateLimiter:
    if limiter is None:
        return InMemoryRateLimiter()
    candidate = cast("object", limiter)
    if (
        isinstance(candidate, type)
        or not isinstance(candidate, RateLimiter)
        or not all(inspect.iscoroutinefunction(getattr(limiter, m)) for m in ("hit", "reset"))
    ):
        msg = "rate_limiter must implement RateLimiter (async hit() and reset())."
        raise ConfigurationError(msg)
    return limiter


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
