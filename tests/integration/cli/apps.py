"""Admins the CLI tests load with ``--app tests.integration.cli.apps:<name>``.

`DATABASE_URL` is set by the test fixtures before the CLI runs.
"""

from __future__ import annotations

import secrets
from typing import ClassVar

from fastapi import FastAPI
from sqlalchemy import String
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from faststudio import Admin, ModelAdmin, ModelUserBackend
from faststudio.contrib.auth import DatabaseAuthBackend
from tests._stubs import StubAuthBackend
from tests.factories.contrib_models import AUTH, Note

DATABASE_URL = ""
SECRET = secrets.token_urlsafe(48)


class HostBase(DeclarativeBase):
    pass


class Staff(HostBase):
    """A host user model with a required, default-less email column (as in the README)."""

    __tablename__ = "cli_staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=False)
    is_admin: Mapped[bool] = mapped_column(default=False)


class NoteAdmin(ModelAdmin, model=Note):
    identity = "notes"
    extra_permissions: ClassVar = {"publish": "Publish notes"}


def model_users() -> Admin:
    """ModelUserBackend over `Staff`."""
    return Admin(
        FastAPI(),
        engine=create_async_engine(DATABASE_URL),
        auth_backend=ModelUserBackend(Staff),
        secret_key=SECRET,
    )


def contrib() -> Admin:
    """contrib.auth with the users/groups/permissions admins and notes."""
    admin = Admin(
        FastAPI(),
        engine=create_async_engine(DATABASE_URL),
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=SECRET,
    )
    admin.register(NoteAdmin)
    return admin


def no_accounts() -> Admin:
    """A custom backend with no capabilities."""
    return Admin(
        FastAPI(),
        engine=create_async_engine(DATABASE_URL),
        auth_backend=StubAuthBackend(),
        secret_key=SECRET,
    )


not_an_admin = object()
fastapi_app = FastAPI()  # an application with no Admin mounted


def env_secret() -> Admin:
    """Reads the secret from FASTSTUDIO_SECRET_KEY (the quickstart's setup)."""
    return Admin(
        FastAPI(), engine=create_async_engine(DATABASE_URL), auth_backend=StubAuthBackend()
    )


def broken() -> Admin:
    """A factory failing with configuration in its message."""
    msg = "could not connect to postgresql://admin:hunter2@db/prod"
    raise RuntimeError(msg)


def binds_only() -> Admin:
    """contrib.auth through a session factory routed only by `binds=`."""
    from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: PLC0415

    from tests.factories.contrib_models import ContribBase  # noqa: PLC0415

    maker = async_sessionmaker(binds={ContribBase: create_async_engine(DATABASE_URL)})
    return Admin(
        FastAPI(), session_maker=maker, auth_backend=DatabaseAuthBackend(AUTH), secret_key=SECRET
    )


def host_app() -> FastAPI:
    """An application factory with one mounted Admin (like examples/basic)."""
    app = FastAPI()
    admin = Admin(
        app,
        engine=create_async_engine(DATABASE_URL),
        auth_backend=DatabaseAuthBackend(AUTH),
        secret_key=SECRET,
    )
    admin.register(NoteAdmin)
    return app


#: The same application as a module-level object; tests set it once DATABASE_URL is known.
mounted_app: FastAPI | None = None


def no_admin_app() -> FastAPI:
    """A FastAPI application without FastStudio."""
    return FastAPI()


def two_admins_app() -> FastAPI:
    """Two Admins mounted on one application: ambiguous."""
    app = FastAPI()
    for base_url in ("/admin", "/staff"):
        Admin(
            app,
            engine=create_async_engine(DATABASE_URL),
            auth_backend=StubAuthBackend(),
            secret_key=SECRET,
            base_url=base_url,
        )
    return app


def not_an_app() -> object:
    """A factory returning something else."""
    return {"app": "nope"}


def needs_arguments(database_url: str) -> Admin:
    """Not a zero-argument factory."""
    return Admin(
        FastAPI(),
        engine=create_async_engine(database_url),
        auth_backend=StubAuthBackend(),
        secret_key=SECRET,
    )


def buggy_factory() -> Admin:
    """A real factory with a bug inside: a TypeError while it runs."""
    msg = "unsupported operand type(s) for +: 'int' and 'str'"
    raise TypeError(msg)


def nested_app() -> FastAPI:
    """The admin's application mounted inside another one."""
    outer = FastAPI()
    outer.mount("/backoffice", host_app())
    return outer


#: A builtin without an inspectable signature (dict): called, returns a dict.
builtin_factory = dict


def wrapped_nested_app() -> FastAPI:
    """The admin's application mounted inside another one, behind middleware."""
    from starlette.middleware.gzip import GZipMiddleware  # noqa: PLC0415

    outer = FastAPI()
    outer.mount("/backoffice", GZipMiddleware(host_app()))
    return outer


def cyclic_app() -> FastAPI:
    """An application mounted into itself (pathological): the search must end."""
    app = host_app()
    app.mount("/loop", app)
    return app


def router_mounted_app() -> FastAPI:
    """The admin's application inside Mount(routes=[...]) (a bare Router)."""
    from starlette.routing import Mount  # noqa: PLC0415

    outer = FastAPI()
    outer.router.routes.append(Mount("/staff", routes=[Mount("/area", app=host_app())]))
    return outer
