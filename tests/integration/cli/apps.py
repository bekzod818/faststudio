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
