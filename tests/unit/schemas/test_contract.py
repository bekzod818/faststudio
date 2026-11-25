"""Pydantic API contract and ModelMeta building (M4)."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ModelAdmin
from faststudio.introspection import _types
from faststudio.schemas import contract
from faststudio.schemas._meta import build_model_meta, build_models_meta
from faststudio.schemas.contract import (
    SCHEMA_VERSION,
    ErrorResponse,
    FieldMeta,
    LoginRequest,
    MetaResponse,
    ModelMeta,
    UserMeta,
    ValidationIssue,
)
from tests._stubs import StubAuthBackend
from tests.factories.models import (
    AllTypes,
    Assignment,
    Audited,
    Country,
    Employee,
    Manager,
    Team,
    Ticket,
    User,
)


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _register(admin: Admin, model: type[Any], **options: Any) -> None:
    admin.register(type(f"{model.__name__}Admin", (ModelAdmin,), dict(options), model=model))


def _user_admin(admin: Admin) -> None:
    _register(
        admin,
        User,
        name="Person",
        icon="users",
        list_display=["id", "email", "is_active", "role", "team_id"],
        search_fields=["email"],
        list_filter=["is_active", "role"],
        ordering=["-created_at", "email"],
        exclude=["password_hash"],
        readonly_fields=["login_count"],
        can_delete=False,
        page_size=50,
    )


# --------------------------------------------------------------------------- contract models


def test_schema_version_is_one() -> None:
    assert SCHEMA_VERSION == "1"


def test_field_type_is_single_source_of_truth() -> None:
    assert contract.FieldType is _types.FieldType


def test_models_reject_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        UserMeta.model_validate({"id": "1", "username": "a", "is_admin": True})


def test_models_are_frozen() -> None:
    user = UserMeta(id="1", username="a")
    with pytest.raises(ValidationError):
        user.username = "b"  # type: ignore[misc]  # frozen on purpose


@pytest.mark.parametrize(
    "code",
    [
        "invalid_query",
        "not_authenticated",
        "invalid_credentials",
        "csrf_failed",
        "forbidden",
        "not_found",
        "method_not_allowed",
        "conflict",
        "validation_error",
        "payload_too_large",
        "rate_limited",
        "internal_error",
    ],
)
def test_error_codes(code: str) -> None:
    body = ErrorResponse.model_validate({"error": {"code": code, "message": "m", "details": None}})
    assert body.error.code == code


def test_unknown_error_code_rejected() -> None:
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"error": {"code": "oops", "message": "m", "details": None}})


@pytest.mark.parametrize(
    ("username", "password"),
    [("", "pw"), ("u", ""), ("u" * 151, "pw"), ("u", "p" * 1025)],
)
def test_login_request_bounds(username: str, password: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(username=username, password=password)


def test_login_request_valid() -> None:
    assert LoginRequest(username="admin", password="p" * 1024).username == "admin"


def test_meta_response_requires_version_one() -> None:
    data = {
        "schema_version": "2",
        "version": "0",
        "title": "t",
        "show_powered_by": True,
        "user": {"id": "1", "username": "a"},
        "models": [],
    }
    with pytest.raises(ValidationError):
        MetaResponse.model_validate(data)
    data["schema_version"] = "1"
    assert MetaResponse.model_validate(data).schema_version == "1"


# --------------------------------------------------------------------------- ModelMeta


def test_model_meta_options(admin: Admin) -> None:
    _user_admin(admin)
    meta = build_model_meta(admin._registry.get("users"), admin._registry)
    assert meta.identity == "users"
    assert meta.name == "Person"
    assert meta.name_plural == "Persons"
    assert meta.icon == "users"
    assert meta.pk_field == "id"
    assert meta.list_display == ["id", "email", "is_active", "role", "team_id"]
    assert meta.search_fields == ["email"]
    assert meta.ordering == ["-created_at", "email"]
    assert meta.page_size == 50
    assert meta.permissions.model_dump() == {
        "view": True,
        "create": True,
        "edit": True,
        "delete": False,
    }


def test_model_meta_filters(admin: Admin) -> None:
    _user_admin(admin)
    meta = build_model_meta(admin._registry.get("users"), admin._registry)
    boolean, choice = meta.list_filter
    assert (boolean.field, boolean.kind, boolean.choices) == ("is_active", "boolean", [])
    assert (choice.field, choice.kind) == ("role", "choice")
    assert [c.value for c in choice.choices] == ["ADMIN", "EDITOR", "VIEWER"]


def test_sortable_fields_are_list_columns_and_ordering(admin: Admin) -> None:
    _user_admin(admin)
    meta = build_model_meta(admin._registry.get("users"), admin._registry)
    assert meta.sortable_fields == ["id", "email", "is_active", "role", "team_id", "created_at"]


def test_json_and_unsupported_columns_are_not_sortable(admin: Admin) -> None:
    _register(
        admin,
        AllTypes,
        can_create=False,
        list_display=["id", "j_json", "x_time", "s_len"],
        ordering=["-id"],
    )
    meta = build_model_meta(admin._registry.get("all_types"), admin._registry)
    assert meta.sortable_fields == ["id", "s_len"]


def test_fields_follow_field_specs(admin: Admin) -> None:
    _user_admin(admin)
    reg = admin._registry.get("users")
    meta = build_model_meta(reg, admin._registry)
    assert [f.name for f in meta.fields] == list(reg.field_specs)
    assert "password_hash" not in [f.name for f in meta.fields]
    by_name = {f.name: f for f in meta.fields}
    spec = reg.field_specs["login_count"]
    assert by_name["login_count"].readonly is True
    assert by_name["login_count"].default == spec.default
    assert by_name["role"].choices is not None
    assert by_name["email"].max_length == 255


def test_relation_resolves_registered_target(admin: Admin) -> None:
    _register(admin, Team)
    _user_admin(admin)
    field = _field(admin, "users", "team_id")
    assert field.relation is not None
    assert field.relation.model_dump() == {
        "target_identity": "teams",
        "target_field": "id",
        "value_type": "integer",
    }


def test_relation_to_unregistered_target_is_null(admin: Admin) -> None:
    _user_admin(admin)
    field = _field(admin, "users", "team_id")
    assert field.relation is not None
    assert field.relation.target_identity is None
    assert field.relation.target_field is None
    assert field.relation.value_type == "integer"


def test_relation_target_registered_later_is_resolved(admin: Admin) -> None:
    _user_admin(admin)
    _register(admin, Team)  # registration order does not matter
    assert _field(admin, "users", "team_id").relation.target_identity == "teams"  # type: ignore[union-attr]


def test_self_and_string_key_relations(admin: Admin) -> None:
    _register(admin, Country)
    _register(admin, Ticket)
    assert _field(admin, "tickets", "parent_id").relation.target_identity == "tickets"  # type: ignore[union-attr]
    country = _field(admin, "tickets", "country_code").relation
    assert country is not None
    assert (country.target_identity, country.target_field) == ("countries", "code")


def test_build_models_meta_in_registration_order(admin: Admin) -> None:
    _register(admin, Team)
    _user_admin(admin)
    assert [m.identity for m in build_models_meta(admin._registry)] == ["teams", "users"]


def test_model_meta_json_round_trip(admin: Admin) -> None:
    _register(admin, AllTypes, can_create=False)
    meta = build_model_meta(admin._registry.get("all_types"), admin._registry)
    assert ModelMeta.model_validate_json(meta.model_dump_json()) == meta


def test_field_meta_has_every_spec_attribute() -> None:
    expected = {
        "name", "label", "type", "nullable", "required", "readonly", "create_only",
        "primary_key", "default", "has_default", "max_length", "min_value", "max_value",
        "choices", "relation", "timezone", "precision", "scale", "help_text", "max_items",
    }  # fmt: skip
    assert set(FieldMeta.model_fields) == expected


def test_field_type_literal_values() -> None:
    assert set(get_args(contract.FieldType)) >= {"foreign_key", "unsupported", "decimal"}


def _field(admin: Admin, identity: str, name: str) -> FieldMeta:
    meta = build_model_meta(admin._registry.get(identity), admin._registry)
    return next(f for f in meta.fields if f.name == name)


# --------------------------------------------------------------------------- review fixes


def test_password_never_in_repr() -> None:
    request = LoginRequest(username="admin", password="S3cret-value")
    assert "S3cret-value" not in repr(request)
    assert "S3cret-value" not in str(request)


def test_password_never_in_validation_errors() -> None:
    secret = "S3cret-value" * 100
    with pytest.raises(ValidationError) as exc_info:
        LoginRequest(username="admin", password=secret)
    assert "S3cret-value" not in str(exc_info.value)


@pytest.mark.parametrize(
    "username",
    [
        "a\x00b",
        "a\nINFO fake",
        "tab\there",
        "a\x7fb",
        "a\x85b",
        "a\x9fb",
        "a\u2028b",
        "a\u2029b",
        "a\u202eb",
        "a\u2066b",
    ],
)
def test_username_rejects_control_and_bidi_characters(username: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(username=username, password="pw")


@pytest.mark.parametrize(
    "username", ["admin", "o'brien@example.com", "Bekzod Ali", "\u0411\u0435\u043a"]
)
def test_username_accepts_normal_names(username: str) -> None:
    assert LoginRequest(username=username, password="pw").username == username


def test_validation_error_details_are_typed() -> None:
    body = ErrorResponse.model_validate(
        {
            "error": {
                "code": "validation_error",
                "message": "Invalid input.",
                "details": [{"loc": ["body", "email", 0], "msg": "bad", "type": "x"}],
            }
        }
    )
    assert body.error.details == [ValidationIssue(loc=["body", "email", 0], msg="bad", type="x")]


@pytest.mark.parametrize(
    "details",
    [
        {"input": "secret"},
        [{"loc": ["a"], "msg": "m", "type": "t", "input": "secret"}],
        [{"loc": ["a"], "msg": "m", "type": "t", "ctx": {"x": 1}}],
        "free text",
    ],
)
def test_error_details_cannot_carry_inputs(details: object) -> None:
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate(
            {"error": {"code": "validation_error", "message": "m", "details": details}}
        )


def test_schema_version_literal_matches_constant() -> None:
    annotation = MetaResponse.model_fields["schema_version"].annotation
    assert get_args(annotation) == (SCHEMA_VERSION,)


def test_sortable_fields_computed_at_register_time(admin: Admin) -> None:
    _user_admin(admin)
    reg = admin._registry.get("users")
    assert reg.sortable_fields == ("id", "email", "is_active", "role", "team_id", "created_at")
    assert build_model_meta(reg, admin._registry).sortable_fields == list(reg.sortable_fields)


def test_relation_prefers_table_owner_over_single_table_subclass(admin: Admin) -> None:
    _register(admin, Manager, identity="managers")  # registered first on purpose
    _register(admin, Employee)
    _register(admin, Assignment)
    relation = _field(admin, "assignments", "employee_id").relation
    assert relation is not None
    assert relation.target_identity == "employees"


def test_relation_falls_back_to_registration_order(admin: Admin) -> None:
    _register(admin, Manager, identity="managers")
    _register(admin, Assignment)
    relation = _field(admin, "assignments", "employee_id").relation
    assert relation is not None
    assert relation.target_identity == "managers"


def test_unsafe_integer_bounds_are_not_published(admin: Admin) -> None:
    _register(admin, Audited, can_create=False)
    meta = build_model_meta(admin._registry.get("audited"), admin._registry)
    by_name = {f.name: f for f in meta.fields}
    assert (by_name["big"].min_value, by_name["big"].max_value) == (None, None)
    assert (by_name["small"].min_value, by_name["small"].max_value) == (-(2**15), 2**15 - 1)
    assert admin._registry.get("audited").field_specs["big"].max_value == 2**63 - 1


def test_excluded_fields_absent_from_entire_serialized_metadata(admin: Admin) -> None:
    _register(admin, Team)
    _register(
        admin,
        User,
        exclude=["password_hash", "bio"],
        list_display=["id", "email"],
        search_fields=["email"],
        ordering=["email"],
        list_filter=["is_active"],
    )
    payload = "".join(m.model_dump_json() for m in build_models_meta(admin._registry))
    assert "password_hash" not in payload
    assert '"bio"' not in payload


def test_unsafe_integer_default_is_not_published() -> None:
    from faststudio.schemas._meta import _safe_default  # noqa: PLC0415 - private helper

    assert _safe_default(2**60) is None
    assert _safe_default(-(2**60)) is None
    assert _safe_default(2**53 - 1) == 2**53 - 1
    assert _safe_default(True) is True
    assert _safe_default("x") == "x"
