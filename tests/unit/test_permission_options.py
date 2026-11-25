"""Permission hooks, `extra_permissions` and `has_perm` (ADR-0011 §2-4, M17)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from faststudio import Admin, ConfigurationError, ModelAdmin
from faststudio.auth.capabilities import ALL
from faststudio.auth.permissions import cache_permissions, has_perm, model_permission
from tests._stubs import StubAuthBackend
from tests.factories.models import Team, User


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _admin_class(model: type[Any] = User, /, **options: Any) -> type[ModelAdmin]:
    return type("UserAdmin", (ModelAdmin,), dict(options), model=model)


def _request(app: FastAPI | None = None) -> Request:
    scope: dict[str, Any] = {"type": "http", "state": {}}
    if app is not None:
        scope["app"] = app
    return Request(scope)


# --------------------------------------------------------------------------- extra_permissions


def test_extra_permissions_become_codenames(admin: Admin) -> None:
    admin.register(_admin_class(identity="people", extra_permissions={"export": "Export people"}))
    assert admin._registry.codenames() == [
        "people.view",
        "people.create",
        "people.edit",
        "people.delete",
        "people.export",
    ]
    assert dict(admin._registry.get("people").extra_permissions) == {"export": "Export people"}


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (["export"], "mapping of key to description"),
        ({"Export": ""}, r"must match \[a-z\]"),
        ({"9lives": ""}, r"must match \[a-z\]"),
        ({"ex-port": ""}, r"must match \[a-z\]"),
        ({"x" * 42: ""}, r"must match \[a-z\]"),
        ({1: ""}, r"must match \[a-z\]"),
        ({"edit": ""}, "built-in actions"),
        ({"view": ""}, "built-in actions"),
        ({"export": None}, "must be a description"),
    ],
)
def test_extra_permissions_are_validated(admin: Admin, value: object, match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        admin.register(_admin_class(extra_permissions=value))


def test_codenames_have_a_length_limit(admin: Admin) -> None:
    identity = "a" * 60
    with pytest.raises(ConfigurationError, match="longer than 100"):
        admin.register(_admin_class(identity=identity, extra_permissions={"b" * 40: ""}))
    admin.register(_admin_class(identity=identity, extra_permissions={"b" * 39: ""}))


# --------------------------------------------------------------------------- hooks


async def _async_hook(cls: type[ModelAdmin], request: Request, obj: object = None) -> bool:
    del cls, request, obj
    return True


def _sync_hook(cls: type[ModelAdmin], request: Request, obj: object = None) -> bool:
    del cls, request, obj
    return True


@pytest.mark.parametrize(
    "hook",
    [
        "has_view_permission",
        "has_create_permission",
        "has_edit_permission",
        "has_delete_permission",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        True,
        _async_hook,  # a plain function: would become an instance method
        staticmethod(_async_hook),
        classmethod(_sync_hook),
    ],
)
def test_hooks_must_be_async_classmethods(admin: Admin, hook: str, value: object) -> None:
    with pytest.raises(ConfigurationError, match=f"{hook} must be an async classmethod"):
        admin.register(_admin_class(**{hook: value}))


def test_async_classmethod_hooks_are_accepted(admin: Admin) -> None:
    admin.register(_admin_class(has_view_permission=classmethod(_async_hook)))


# --------------------------------------------------------------------------- has_perm


async def test_has_perm_outside_an_admin_request_fails_loudly() -> None:
    with pytest.raises(ConfigurationError, match="only during a FastStudio admin API request"):
        await has_perm(_request(), "users.view")


async def test_has_perm_reads_the_cached_permissions() -> None:
    request = _request()
    cache_permissions(request, frozenset({"users.edit"}))
    assert await has_perm(request, "users.view")
    assert await has_perm(request, "users.edit")
    assert not await has_perm(request, "users.delete")
    cache_permissions(request, ALL)
    assert await has_perm(request, "anything.at_all")


async def test_default_hooks_need_a_mounted_admin() -> None:
    request = _request(FastAPI())
    cache_permissions(request, frozenset())
    with pytest.raises(ConfigurationError, match=r"inside a mounted faststudio\.Admin"):
        await model_permission(request, _admin_class(), "view")


async def test_default_hooks_need_a_registered_class(admin: Admin) -> None:
    request = _request(admin._sub_app)
    cache_permissions(request, frozenset({"teams.view"}))
    with pytest.raises(ConfigurationError, match="is not registered"):
        await model_permission(request, _admin_class(Team), "view")


async def test_default_hooks_combine_the_static_flag_and_the_permission(admin: Admin) -> None:
    locked = admin.register(_admin_class(identity="people", can_delete=False))
    request = _request(admin._sub_app)
    cache_permissions(request, ALL)
    assert await locked.has_edit_permission(request)
    assert not await locked.has_delete_permission(request)  # the flag wins, even with ALL
    cache_permissions(request, frozenset({"people.view"}))
    assert await locked.has_view_permission(request)
    assert not await locked.has_create_permission(request)
    assert not await locked.has_edit_permission(request, object())
