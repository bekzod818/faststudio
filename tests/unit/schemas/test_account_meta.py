"""ModelMeta.account tells the SPA which own-account fields are protected (ADR-0009)."""

from __future__ import annotations

from typing import Any

import pytest

from faststudio import ModelAdmin, ModelUserBackend
from faststudio.registry import Registry, resolve_model_admin
from faststudio.schemas._meta import build_model_meta, build_models_meta
from tests.factories.models import AdminUser, Team


def _registry(*admin_classes: type[ModelAdmin]) -> Registry:
    registry = Registry()
    for admin_class in admin_classes:
        registry.add(resolve_model_admin(admin_class, max_page_size=100))
    return registry


def _admin_class(**options: Any) -> type[ModelAdmin]:
    return type(
        "UsersAdmin",
        (ModelAdmin,),
        {"list_display": ("id", "username"), **options},
        model=AdminUser,
    )


class TeamAdmin(ModelAdmin, model=Team):
    list_display = ("id", "name")


@pytest.mark.parametrize(
    ("options", "protected"),
    [
        ({"exclude": ("password_hash",)}, ["is_active", "is_admin"]),
        ({"exclude": ("password_hash", "is_admin")}, ["is_active"]),
        ({"exclude": ("password_hash",), "readonly_fields": ("is_active",)}, ["is_admin"]),
        ({"exclude": ("password_hash", "is_active", "is_admin")}, []),
    ],
)
def test_user_model_lists_its_visible_writable_sign_in_flags(
    options: dict[str, Any], protected: list[str]
) -> None:
    registry = _registry(_admin_class(**options))
    meta = build_model_meta(
        registry.get("admin_users"), registry, guard=ModelUserBackend(AdminUser)
    )
    assert meta.account is not None
    assert meta.account.protected_fields == protected


def test_backend_flags_follow_its_configuration() -> None:
    registry = _registry(_admin_class(exclude=("password_hash",)))
    backend = ModelUserBackend(AdminUser, is_admin_field=None)
    meta = build_model_meta(registry.get("admin_users"), registry, guard=backend)
    assert meta.account is not None
    assert meta.account.protected_fields == ["is_active"]


def test_other_models_and_unguarded_backends_have_no_account() -> None:
    registry = _registry(_admin_class(exclude=("password_hash",)), TeamAdmin)
    guarded = {
        m.identity: m.account
        for m in build_models_meta(registry, guard=ModelUserBackend(AdminUser))
    }
    assert guarded["teams"] is None
    assert guarded["admin_users"] is not None
    assert all(m.account is None for m in build_models_meta(registry))
