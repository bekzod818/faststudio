"""SQLAlchemy column -> FieldSpec introspection (M3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ConfigurationError, ModelAdmin
from faststudio.introspection._fields import (
    Choice,
    FieldSpec,
    build_field_spec,
    humanize,
    json_default,
    looks_sensitive,
)
from faststudio.registry import RegisteredModel
from tests._stubs import StubAuthBackend
from tests.factories.models import (
    AllTypes,
    Audited,
    Clock,
    Country,
    Employee,
    Engineer,
    Hooked,
    Orphan,
    Role,
    Team,
    Ticket,
    User,
    Versioned,
)


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _register(admin: Admin, model: type[Any], **options: Any) -> RegisteredModel:
    cls = type(f"{model.__name__}Admin", (ModelAdmin,), dict(options), model=model)
    admin.register(cls)
    return next(r for r in admin._registry if r.model is model)


@pytest.fixture
def all_types(admin: Admin) -> dict[str, FieldSpec]:
    return dict(_register(admin, AllTypes, can_create=False).field_specs)


@pytest.fixture
def audited(admin: Admin) -> dict[str, FieldSpec]:
    return dict(_register(admin, Audited, can_create=False).field_specs)


# --------------------------------------------------------------------------- type mapping

TYPE_TABLE = [
    ("id", "integer"),
    ("s_len", "string"),
    ("s_unicode", "string"),
    ("s_nolen", "string"),
    ("t_text", "text"),
    ("t_unicode", "text"),
    ("i_int", "integer"),
    ("i_small", "integer"),
    ("i_big", "integer"),
    ("f_float", "float"),
    ("f_double", "float"),
    ("d_numeric", "decimal"),
    ("d_numeric_float", "float"),
    ("b_bool", "boolean"),
    ("dt_date", "date"),
    ("dt_naive", "datetime"),
    ("dt_aware", "datetime"),
    ("e_enum", "enum"),
    ("e_letters", "enum"),
    ("e_strings", "enum"),
    ("j_json", "json"),
    ("j_jsonb", "json"),
    ("u_uuid", "uuid"),
    ("u_pg_uuid", "uuid"),
    ("x_time", "unsupported"),
    ("x_interval", "unsupported"),
    ("x_binary", "unsupported"),
    ("x_pickle", "unsupported"),
    ("x_array", "unsupported"),
    ("x_variant", "unsupported"),
    ("fk_team", "foreign_key"),
    ("g_computed", "integer"),
    ("wrapped", "string"),
]


@pytest.mark.parametrize(("field", "expected"), TYPE_TABLE)
def test_type_mapping(all_types: dict[str, FieldSpec], field: str, expected: str) -> None:
    assert all_types[field].type == expected


def test_every_column_is_classified(all_types: dict[str, FieldSpec]) -> None:
    assert list(all_types) == [name for name, _ in TYPE_TABLE]


def test_plain_type_decorator_is_classified_by_impl(all_types: dict[str, FieldSpec]) -> None:
    assert all_types["wrapped"].type == "string"
    assert not all_types["wrapped"].readonly
    assert all_types["wrapped"].max_length == 100


def test_value_converting_type_decorator_is_unsupported(audited: dict[str, FieldSpec]) -> None:
    spec = audited["payload"]
    assert spec.type == "unsupported"
    assert spec.readonly
    assert spec.max_length is None


# --------------------------------------------------------------------------- flags


def test_autoincrement_primary_key(all_types: dict[str, FieldSpec]) -> None:
    pk = all_types["id"]
    assert pk.primary_key
    assert pk.readonly
    assert not pk.create_only
    assert not pk.required
    assert not pk.nullable
    assert pk.label == "ID"


def test_required_string_with_length_and_comment(all_types: dict[str, FieldSpec]) -> None:
    spec = all_types["s_len"]
    assert spec.required
    assert not spec.nullable
    assert not spec.readonly
    assert spec.max_length == 50
    assert spec.help_text == "A short string"
    assert spec.label == "S len"


def test_nullable_string_without_length(all_types: dict[str, FieldSpec]) -> None:
    spec = all_types["s_nolen"]
    assert spec.nullable
    assert not spec.required
    assert spec.max_length is None


@pytest.mark.parametrize(
    ("field", "default"),
    [("i_int", 7), ("d_numeric", "1.50"), ("dt_date", "2026-01-02"), ("e_enum", "EDITOR")],
)
def test_scalar_defaults_are_json_safe(
    all_types: dict[str, FieldSpec], field: str, default: object
) -> None:
    spec = all_types[field]
    assert spec.default == default
    assert spec.has_default
    assert not spec.required


@pytest.mark.parametrize("field", ["dt_naive", "j_json", "u_uuid", "b_bool"])
def test_callable_and_server_defaults_are_flagged_not_exposed(
    all_types: dict[str, FieldSpec], field: str
) -> None:
    spec = all_types[field]
    assert spec.has_default
    assert spec.default is None
    assert not spec.required


def test_decimal_default_is_a_string(audited: dict[str, FieldSpec]) -> None:
    assert audited["price"].default == "1.5"


def test_plain_default_is_published(audited: dict[str, FieldSpec]) -> None:
    assert audited["plain_note"].default == "hello"


@pytest.mark.parametrize("field", ["api_token", "blob"])
def test_sensitive_and_unsupported_defaults_are_hidden(
    audited: dict[str, FieldSpec], field: str
) -> None:
    spec = audited[field]
    assert spec.default is None
    assert spec.has_default


def test_decimal_precision_and_scale(all_types: dict[str, FieldSpec]) -> None:
    assert (all_types["d_numeric"].precision, all_types["d_numeric"].scale) == (10, 2)
    assert all_types["d_numeric_float"].precision is None


def test_timezone_only_for_datetime_fields(all_types: dict[str, FieldSpec]) -> None:
    assert all_types["dt_naive"].timezone is False
    assert all_types["dt_aware"].timezone is True
    assert all_types["dt_date"].timezone is None
    assert all_types["x_interval"].timezone is None


@pytest.mark.parametrize(
    ("field", "low", "high"),
    [
        ("small", -(2**15), 2**15 - 1),
        ("seq_no", -(2**31), 2**31 - 1),
        ("big", -(2**63), 2**63 - 1),
    ],
)
def test_integer_ranges(audited: dict[str, FieldSpec], field: str, low: int, high: int) -> None:
    assert (audited[field].min_value, audited[field].max_value) == (low, high)


def test_non_integers_have_no_range(audited: dict[str, FieldSpec]) -> None:
    assert audited["price"].min_value is None
    assert audited["plain_note"].max_value is None


def test_enum_class_choices_use_member_names(all_types: dict[str, FieldSpec]) -> None:
    assert all_types["e_enum"].choices == (
        Choice("ADMIN", "Admin"),
        Choice("EDITOR", "Editor"),
        Choice("VIEWER", "Viewer"),
    )
    assert all_types["e_letters"].choices == (
        Choice("A_ONE", "A one"),
        Choice("IN_PROGRESS", "In progress"),
    )


def test_string_enum_choices(all_types: dict[str, FieldSpec]) -> None:
    assert all_types["e_strings"].choices == (
        Choice("draft", "Draft"),
        Choice("published", "Published"),
    )


def test_non_enum_fields_have_no_choices(all_types: dict[str, FieldSpec]) -> None:
    assert all_types["s_len"].choices is None


@pytest.mark.parametrize(
    "field", ["x_time", "x_interval", "x_binary", "x_pickle", "x_array", "x_variant"]
)
def test_unsupported_fields_are_readonly_and_optional(
    all_types: dict[str, FieldSpec], field: str
) -> None:
    spec = all_types[field]
    assert spec.readonly
    assert not spec.required


def test_computed_column_is_readonly(all_types: dict[str, FieldSpec]) -> None:
    spec = all_types["g_computed"]
    assert spec.readonly
    assert not spec.required


@pytest.mark.parametrize(
    "field", ["updated_at", "touched_at", "trigger_set", "seq_no", "dialect_fk", "variant_fk"]
)
def test_maintained_or_unvalidatable_columns_are_readonly(
    audited: dict[str, FieldSpec], field: str
) -> None:
    spec = audited[field]
    assert spec.readonly
    assert not spec.required


def test_plain_columns_stay_writable(audited: dict[str, FieldSpec]) -> None:
    assert not audited["plain_note"].readonly
    assert not audited["price"].readonly


def test_version_column_is_managed(admin: Admin) -> None:
    specs = _register(admin, Versioned).field_specs
    assert specs["version"].readonly
    assert not specs["version"].required
    assert not specs["title"].readonly
    assert specs["title"].required


@pytest.mark.parametrize("model", [Employee, Engineer])
def test_polymorphic_discriminator_is_managed(admin: Admin, model: type[Any]) -> None:
    spec = _register(admin, model).field_specs["kind"]
    assert spec.readonly
    assert not spec.required


# --------------------------------------------------------------------------- primary keys


def test_natural_primary_key_is_required_and_create_only(admin: Admin) -> None:
    spec = _register(admin, Country).field_specs["code"]
    assert spec.primary_key
    assert spec.required
    assert not spec.readonly
    assert spec.create_only
    assert spec.max_length == 2


def test_readonly_natural_primary_key_is_not_create_only(admin: Admin) -> None:
    reg = _register(admin, Country, readonly_fields=["code"], can_create=False)
    spec = reg.field_specs["code"]
    assert spec.readonly
    assert not spec.create_only


def test_primary_key_with_default_is_server_chosen(admin: Admin) -> None:
    spec = _register(admin, Ticket).field_specs["id"]
    assert spec.type == "uuid"
    assert spec.readonly  # clients cannot choose their own primary key
    assert not spec.create_only
    assert not spec.required
    assert spec.has_default


def test_non_key_fields_are_never_create_only(all_types: dict[str, FieldSpec]) -> None:
    assert not any(s.create_only for s in all_types.values())


def test_identity_column_is_readonly(admin: Admin) -> None:
    spec = _register(admin, Ticket).field_specs["number"]
    assert spec.readonly
    assert not spec.required


def test_joined_inheritance_primary_key_is_generated_not_a_relation(admin: Admin) -> None:
    spec = _register(admin, Engineer).field_specs["id"]
    assert spec.type == "integer"
    assert spec.relation is None
    assert spec.readonly
    assert not spec.required


# --------------------------------------------------------------------------- relations


def test_foreign_key_relation(all_types: dict[str, FieldSpec]) -> None:
    spec = all_types["fk_team"]
    assert spec.relation is not None
    assert spec.relation.target is Team.__table__.c.id
    assert spec.relation.value_type == "integer"
    assert spec.nullable
    assert spec.label == "Fk team"


def test_only_foreign_keys_have_relations(all_types: dict[str, FieldSpec]) -> None:
    assert [k for k, s in all_types.items() if s.relation is not None] == ["fk_team"]


@pytest.mark.parametrize(
    ("field", "value_type", "target", "label"),
    [
        ("parent_id", "uuid", "tickets.id", "Parent"),
        ("country_code", "string", "countries.code", "Country code"),
    ],
)
def test_foreign_key_value_types(
    admin: Admin, field: str, value_type: str, target: str, label: str
) -> None:
    spec = _register(admin, Ticket).field_specs[field]
    assert spec.type == "foreign_key"
    assert spec.relation is not None
    assert spec.relation.value_type == value_type
    assert str(spec.relation.target) == target
    assert spec.label == label


def test_composite_foreign_key_column_is_plain(admin: Admin) -> None:
    spec = _register(admin, Ticket).field_specs["member_user"]
    assert spec.type == "integer"
    assert spec.relation is None


def test_foreign_key_to_non_primary_key_is_plain_value(audited: dict[str, FieldSpec]) -> None:
    spec = audited["key_ref"]
    assert spec.type == "string"
    assert spec.relation is None
    assert not spec.readonly


@pytest.mark.parametrize("field", ["dialect_fk", "variant_fk"])
def test_foreign_key_with_unsupported_own_type_is_unsupported(
    audited: dict[str, FieldSpec], field: str
) -> None:
    assert audited[field].type == "unsupported"
    assert audited[field].relation is None


def test_unresolvable_foreign_key_is_configuration_error(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match=r"'ghost_id'.*cannot be resolved"):
        _register(admin, Orphan)


def test_column_is_the_canonical_table_column(all_types: dict[str, FieldSpec]) -> None:
    for spec in all_types.values():
        assert spec.column.table.c[spec.column.key] is spec.column


# --------------------------------------------------------------------------- options


def test_labels_from_column_labels_and_humanized(admin: Admin) -> None:
    specs = _register(
        admin, User, exclude=["password_hash"], column_labels={"full_name": "Display name"}
    ).field_specs
    assert specs["full_name"].label == "Display name"
    assert specs["created_at"].label == "Created at"
    assert specs["team_id"].label == "Team"
    assert specs["is_active"].label == "Is active"


def test_readonly_fields_option(admin: Admin) -> None:
    specs = _register(
        admin, User, exclude=["password_hash"], readonly_fields=["email", "login_count"]
    ).field_specs
    assert specs["email"].readonly
    assert not specs["email"].required  # cannot be required if it cannot be provided
    assert specs["login_count"].readonly
    assert not specs["full_name"].readonly


def test_excluded_fields_have_no_spec(admin: Admin) -> None:
    specs = _register(admin, User, exclude=["password_hash"]).field_specs
    assert "password_hash" not in specs
    assert next(iter(specs)) == "id"


def test_field_specs_match_visible_fields(admin: Admin) -> None:
    reg = _register(admin, User, exclude=["password_hash", "bio"])
    assert list(reg.field_specs) == list(reg.fields)


# --------------------------------------------------------------------------- create warning


def _create_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "can_create" in r.getMessage()]


def test_warns_when_create_cannot_succeed(admin: Admin, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _register(admin, User, exclude=["password_hash"], readonly_fields=["email"])
    (message,) = _create_warnings(caplog)
    assert "'password_hash'" in message
    assert "'email'" in message


def test_create_warning_covers_unsupported_required_fields(
    admin: Admin, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _register(admin, Clock)
    (message,) = _create_warnings(caplog)
    assert "'at'" in message


def test_create_warning_ignores_managed_and_create_only_fields(
    admin: Admin, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _register(admin, Versioned)
        _register(admin, Country)
        _register(admin, Employee)
    assert _create_warnings(caplog) == []


def test_no_create_warning_when_create_disabled(
    admin: Admin, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _register(admin, User, exclude=["password_hash"], can_create=False)
    assert _create_warnings(caplog) == []


def test_no_create_warning_when_all_required_fields_writable(
    admin: Admin, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        _register(admin, Team)
    assert caplog.records == []


# --------------------------------------------------------------------------- helpers


class _Opaque:
    pass


@pytest.mark.parametrize(
    ("value", "field_type", "expected"),
    [
        (None, None, None),
        (True, None, True),
        (3, None, 3),
        (1.5, None, 1.5),
        ("x", None, "x"),
        (Decimal("2.10"), None, "2.10"),
        (1.5, "decimal", "1.5"),
        (2, "decimal", "2"),
        (True, "decimal", True),
        (date(2026, 1, 2), None, "2026-01-02"),
        (datetime(2026, 1, 2, 3, 4, 5), None, "2026-01-02T03:04:05"),
        (uuid.UUID(int=1), None, "00000000-0000-0000-0000-000000000001"),
        (Role.ADMIN, None, "ADMIN"),
        ({"a": [1, 2]}, None, {"a": [1, 2]}),
        ([1, "x"], None, [1, "x"]),
    ],
)
def test_json_default_serializes(value: object, field_type: Any, expected: object) -> None:
    assert json_default(value, field_type) == expected


@pytest.mark.parametrize(
    ("value", "field_type"),
    [
        (_Opaque(), None),
        ({"a": _Opaque()}, None),
        (float("nan"), None),
        (float("inf"), "decimal"),
        (Decimal("NaN"), None),
        (b"raw", None),
        ({1: "x"}, None),
    ],
)
def test_json_default_rejects_unserializable(value: object, field_type: Any) -> None:
    assert json_default(value, field_type) is None


def test_build_spec_for_standalone_column() -> None:
    column: Column[Any] = Column("code", String(5), nullable=False)
    spec = build_field_spec("code", column, label=None, readonly=False)
    assert spec.type == "string"
    assert spec.required
    assert spec.label == "Code"
    other: Column[Any] = Column("n", Integer, nullable=True, default=lambda: 1)
    assert build_field_spec("n", other, label="N", readonly=False).has_default


@pytest.mark.parametrize(
    ("name", "strip_id", "expected"),
    [
        ("created_at", False, "Created at"),
        ("IN_PROGRESS", False, "In progress"),
        ("user_api_key", False, "User API key"),
        ("id", True, "ID"),
        ("team_id", True, "Team"),
        ("team_id", False, "Team ID"),
        ("_private", False, "Private"),
        ("___", False, "___"),
    ],
)
def test_humanize(name: str, strip_id: bool, expected: str) -> None:
    assert humanize(name, strip_id=strip_id) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("api_token", True), ("passwordHash", True), ("hashtag", False), ("plain_note", False)],
)
def test_looks_sensitive(name: str, expected: bool) -> None:
    assert looks_sensitive(name) is expected


@pytest.mark.parametrize(
    "field", ["bind_proc", "result_proc", "bind_expr", "col_expr", "string_sub"]
)
def test_value_hooks_make_a_type_unsupported(admin: Admin, field: str) -> None:
    spec = _register(admin, Hooked, can_create=False).field_specs[field]
    assert spec.type == "unsupported"
    assert spec.readonly
    assert spec.max_length is None


def test_plain_subclass_of_builtin_type_is_classified(admin: Admin) -> None:
    spec = _register(admin, Hooked, can_create=False).field_specs["plain_sub"]
    assert spec.type == "string"
    assert spec.max_length == 30


def test_decimal_default_on_float_field_is_a_number(admin: Admin) -> None:
    assert _register(admin, Hooked, can_create=False).field_specs["ratio"].default == 1.5


@pytest.mark.parametrize(
    ("value", "expected"), [(Decimal("2.5"), 2.5), (3, 3.0), (float("inf"), None)]
)
def test_json_default_float_fields(value: object, expected: object) -> None:
    assert json_default(value, "float") == expected
