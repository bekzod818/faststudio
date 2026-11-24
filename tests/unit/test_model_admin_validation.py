"""ModelAdmin declaration and register() validation (M2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast

import pytest
from fastapi import FastAPI
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ConfigurationError, ModelAdmin
from tests._stubs import StubAuthBackend
from tests.factories.models import (
    Account,
    Address,
    Category,
    Engineer,
    Gadget,
    Membership,
    NotMapped,
    Team,
    User,
    Vault,
)


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _admin_class(model: type[Any] = User, /, **options: Any) -> type[ModelAdmin]:
    """Build a ModelAdmin subclass dynamically, the way users would declare one."""
    return type("UserAdmin", (ModelAdmin,), dict(options), model=model)


# --------------------------------------------------------------------------- happy path


def test_register_returns_class_and_works_as_decorator(admin: Admin) -> None:
    @admin.register
    class TeamAdmin(ModelAdmin, model=Team):
        list_display = ("id", "name")

    assert TeamAdmin.model is Team
    registered = admin._registry.get("teams")
    assert registered.admin_class is TeamAdmin
    assert registered.model is Team


def test_defaults(admin: Admin) -> None:
    admin.register(_admin_class())
    reg = admin._registry.get("users")
    assert reg.identity == "users"
    assert reg.name == "User"
    assert reg.name_plural == "Users"
    assert reg.icon is None
    assert reg.pk_field == "id"
    # default list_display: pk + first 4 other visible columns, in declaration order
    assert reg.list_display == ("id", "email", "full_name", "bio", "handle")
    assert reg.search_fields == ()
    assert reg.list_filter == ()
    assert reg.ordering == ()
    assert reg.page_size == 25
    assert reg.can_create
    assert reg.can_edit
    assert reg.can_delete


def test_full_declaration(admin: Admin) -> None:
    admin.register(
        _admin_class(
            identity="people",
            name="Person",
            name_plural="People",
            icon="users-round",
            list_display=["id", "email", "is_active", "role", "created_at"],
            search_fields=["email", "full_name", "bio", "handle"],
            list_filter=["is_active", "role"],
            ordering=["-created_at", "email"],
            page_size=50,
            readonly_fields=["created_at", "login_count"],
            exclude=["password_hash"],
            column_labels={"full_name": "Full name"},
            can_create=False,
            can_delete=False,
        )
    )
    reg = admin._registry.get("people")
    assert reg.name_plural == "People"
    assert reg.search_fields == ("email", "full_name", "bio", "handle")
    assert reg.list_filter == ("is_active", "role")
    assert reg.ordering == (("created_at", True), ("email", False))
    assert reg.readonly_fields == frozenset({"created_at", "login_count"})
    assert reg.exclude == frozenset({"password_hash"})
    assert "password_hash" not in reg.fields
    assert reg.column_labels == {"full_name": "Full name"}
    assert (reg.can_create, reg.can_edit, reg.can_delete) == (False, True, False)


def test_default_list_display_skips_excluded(admin: Admin) -> None:
    admin.register(_admin_class(exclude=("email", "bio")))
    assert admin._registry.get("users").list_display == (
        "id",
        "full_name",
        "handle",
        "is_active",
        "role",
    )


@pytest.mark.parametrize(
    ("model", "singular", "plural"),
    [(Category, "Category", "Categories"), (Address, "Address", "Addresses")],
)
def test_default_names_pluralize(
    admin: Admin, model: type[Any], singular: str, plural: str
) -> None:
    admin.register(_admin_class(model))
    reg = admin._registry.get(model.__tablename__)
    assert (reg.name, reg.name_plural) == (singular, plural)


def test_options_inherit_from_intermediate_base(admin: Admin) -> None:
    class BaseAdmin(ModelAdmin):
        page_size = 10
        can_delete = False

    class TeamAdmin(BaseAdmin, model=Team):
        pass

    admin.register(TeamAdmin)
    reg = admin._registry.get("teams")
    assert (reg.page_size, reg.can_delete) == (10, False)


def test_registry_iterates_in_registration_order(admin: Admin) -> None:
    admin.register(_admin_class(Team))
    admin.register(_admin_class(User))
    assert [r.identity for r in admin._registry] == ["teams", "users"]
    assert len(admin._registry) == 2


def test_unknown_identity_lookup_raises_keyerror(admin: Admin) -> None:
    with pytest.raises(KeyError):
        admin._registry.get("nope")


# --------------------------------------------------------------------------- rejected


def _assert_rejected(admin: Admin, match: str, model: type[Any] = User, /, **options: Any) -> None:
    with pytest.raises(ConfigurationError, match=match):
        admin.register(_admin_class(model, **options))


@pytest.mark.parametrize("candidate", [object(), "UserAdmin", ModelAdmin, int])
def test_register_requires_modeladmin_subclass(admin: Admin, candidate: Any) -> None:
    with pytest.raises(ConfigurationError, match="ModelAdmin subclass"):
        admin.register(candidate)


def test_register_instance_rejected(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="ModelAdmin subclass"):
        admin.register(cast(Any, _admin_class()()))  # an instance, not the class


def test_model_required(admin: Admin) -> None:
    class NoModelAdmin(ModelAdmin):
        pass

    with pytest.raises(ConfigurationError, match="no model"):
        admin.register(NoModelAdmin)


def test_unmapped_model_rejected(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="not a mapped SQLAlchemy class"):
        admin.register(_admin_class(NotMapped))


def test_composite_primary_key_rejected(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="composite primary key"):
        admin.register(_admin_class(Membership))


def test_duplicate_identity_rejected(admin: Admin) -> None:
    admin.register(_admin_class(Team, identity="things"))
    with pytest.raises(ConfigurationError, match="identity 'things' is already registered"):
        admin.register(_admin_class(User, identity="things"))


def test_duplicate_identity_leaves_registry_unchanged(admin: Admin) -> None:
    admin.register(_admin_class(Team, identity="things"))
    with pytest.raises(ConfigurationError):
        admin.register(_admin_class(User, identity="things"))
    assert len(admin._registry) == 1
    assert admin._registry.get("things").model is Team


def test_duplicate_model_rejected(admin: Admin) -> None:
    admin.register(_admin_class(Team))
    with pytest.raises(ConfigurationError, match="Team is already registered"):
        admin.register(_admin_class(Team, identity="teams2"))


def test_failed_registration_leaves_registry_unchanged(admin: Admin) -> None:
    with pytest.raises(ConfigurationError):
        admin.register(_admin_class(list_display=["nope"]))
    assert len(admin._registry) == 0
    admin.register(_admin_class())  # same model can still be registered


@pytest.mark.parametrize(
    "identity", ["", "Users", "user admin", "users/1", "-users", "a" * 65, "../x", "users?", 5]
)
def test_invalid_identity(admin: Admin, identity: Any) -> None:
    _assert_rejected(admin, "identity", identity=identity)


@pytest.mark.parametrize(
    "option",
    ["list_display", "search_fields", "list_filter", "ordering", "readonly_fields", "exclude"],
)
def test_string_instead_of_sequence_rejected(admin: Admin, option: str) -> None:
    _assert_rejected(admin, f"{option} must be a list or tuple", **{option: "email"})


@pytest.mark.parametrize(
    "option",
    ["list_display", "search_fields", "list_filter", "ordering", "readonly_fields", "exclude"],
)
def test_unknown_field_rejected_with_available_fields(admin: Admin, option: str) -> None:
    with pytest.raises(ConfigurationError, match=f"{option}.*'nope'") as exc_info:
        admin.register(_admin_class(**{option: ["nope"]}))
    assert "email" in str(exc_info.value)  # lists available fields


def test_column_name_is_not_accepted_for_attribute_key(admin: Admin) -> None:
    # The column is called "name" but the mapped attribute is "full_name".
    _assert_rejected(admin, "'name'", list_display=["name"])


@pytest.mark.parametrize(
    "option", ["list_display", "search_fields", "list_filter", "readonly_fields", "exclude"]
)
def test_non_str_entry_rejected(admin: Admin, option: str) -> None:
    _assert_rejected(admin, option, **{option: [1]})


@pytest.mark.parametrize(
    "option", ["list_display", "search_fields", "list_filter", "readonly_fields", "exclude"]
)
def test_duplicate_entries_rejected(admin: Admin, option: str) -> None:
    field = {"search_fields": "email", "list_filter": "is_active"}.get(option, "bio")
    _assert_rejected(admin, "duplicate", **{option: [field, field]})


@pytest.mark.parametrize(
    "field", ["id", "is_active", "role", "login_count", "created_at", "team_id"]
)
def test_search_fields_must_be_text(admin: Admin, field: str) -> None:
    _assert_rejected(admin, "search_fields.*text", search_fields=[field])


@pytest.mark.parametrize("field", ["email", "bio", "login_count", "created_at", "team_id"])
def test_list_filter_must_be_boolean_or_enum(admin: Admin, field: str) -> None:
    _assert_rejected(admin, "list_filter.*boolean or enum", list_filter=[field])


@pytest.mark.parametrize("entry", ["", "-", "--email", "-nope", "+email", 1, None])
def test_invalid_ordering_entry(admin: Admin, entry: str) -> None:
    _assert_rejected(admin, "ordering", ordering=[entry])


def test_ordering_field_twice_rejected(admin: Admin) -> None:
    _assert_rejected(admin, "duplicate", ordering=["email", "-email"])


@pytest.mark.parametrize(
    "option",
    ["list_display", "search_fields", "ordering", "readonly_fields"],
)
def test_excluded_field_cannot_be_used_elsewhere(admin: Admin, option: str) -> None:
    value = ["-password_hash"] if option == "ordering" else ["password_hash"]
    _assert_rejected(admin, "excluded", exclude=["password_hash"], **{option: value})


def test_excluded_field_cannot_be_filtered(admin: Admin) -> None:
    _assert_rejected(admin, "excluded", exclude=["is_active"], list_filter=["is_active"])


def test_excluded_field_cannot_be_labelled(admin: Admin) -> None:
    _assert_rejected(
        admin, "excluded", exclude=["password_hash"], column_labels={"password_hash": "Hash"}
    )


def test_primary_key_cannot_be_excluded(admin: Admin) -> None:
    _assert_rejected(admin, "primary key", exclude=["id"])


@pytest.mark.parametrize(
    "labels", [{"nope": "X"}, {"email": ""}, {"email": 1}, ["email"], {1: "x"}]
)
def test_invalid_column_labels(admin: Admin, labels: Any) -> None:
    _assert_rejected(admin, "column_labels", column_labels=labels)


@pytest.mark.parametrize("size", [0, -1, True, "25", 2.5, 101])
def test_invalid_page_size(admin: Admin, size: Any) -> None:
    _assert_rejected(admin, "page_size", page_size=size)


def _small_admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(
        app, engine=engine, auth_backend=auth_backend, secret_key=secret_key, max_page_size=20
    )


def test_default_page_size_adapts_to_smaller_max(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    small = _small_admin(app, engine, auth_backend, secret_key)
    small.register(_admin_class())  # built-in default 25 is capped, not an error
    assert small._registry.get("users").page_size == 20


def test_explicit_page_size_above_max_rejected(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    small = _small_admin(app, engine, auth_backend, secret_key)
    with pytest.raises(ConfigurationError, match="max_page_size"):
        small.register(_admin_class(page_size=25))
    small.register(_admin_class(page_size=20))


def test_inherited_page_size_above_max_rejected(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> None:
    class BaseAdmin(ModelAdmin):
        page_size = 50

    class TeamAdmin(BaseAdmin, model=Team):
        pass

    with pytest.raises(ConfigurationError, match="max_page_size"):
        _small_admin(app, engine, auth_backend, secret_key).register(TeamAdmin)


@pytest.mark.parametrize("option", ["can_create", "can_edit", "can_delete"])
@pytest.mark.parametrize("value", [1, "yes", None])
def test_permission_flags_must_be_bool(admin: Admin, option: str, value: Any) -> None:
    _assert_rejected(admin, option, **{option: value})


@pytest.mark.parametrize(
    ("option", "value"), [("name", ""), ("name", 1), ("name_plural", " "), ("name", "x" * 101)]
)
def test_invalid_names(admin: Admin, option: str, value: Any) -> None:
    _assert_rejected(admin, option, **{option: value})


@pytest.mark.parametrize("icon", ["", "Users", "users icon", "<svg>", 3, "a" * 65])
def test_invalid_icon(admin: Admin, icon: Any) -> None:
    _assert_rejected(admin, "icon", icon=icon)


@pytest.mark.parametrize(
    ("typo", "suggestion"),
    [
        ("list_filters", "list_filter"),
        ("search_field", "search_fields"),
        ("readonly", "readonly_fields"),
        ("list_per_page", "page_size"),
        ("excludes", "exclude"),
    ],
)
def test_misspelled_option_rejected_with_suggestion(
    admin: Admin, typo: str, suggestion: str
) -> None:
    _assert_rejected(admin, f"unknown option '{typo}'.*'{suggestion}'", **{typo: ["email"]})


def test_private_attributes_and_methods_allowed(admin: Admin) -> None:
    class TeamAdmin(ModelAdmin, model=Team):
        _team_color = "blue"
        _private = 1

        def helper(self) -> str:
            return "ok"

        @property
        def computed(self) -> str:
            return "ok"

        @classmethod
        def build(cls) -> str:
            return "ok"

        @staticmethod
        def util() -> str:
            return "ok"

    admin.register(TeamAdmin)


def test_expression_attributes_are_not_fields(admin: Admin) -> None:
    admin.register(_admin_class(Team))
    assert "name_upper" not in admin._registry.get("teams").fields
    with pytest.raises(ConfigurationError, match="unknown field 'name_upper'"):
        admin.register(_admin_class(Team, identity="teams2", list_display=["name_upper"]))


def test_model_kwarg_must_be_a_class() -> None:
    with pytest.raises(ConfigurationError, match="model="):

        class Bad(ModelAdmin, model="users"):  # type: ignore[arg-type]  # wrong type on purpose
            pass


# --------------------------------------------------------------------------- review fixes


@pytest.mark.parametrize("attr", ["team_color", "hidden_fields", "exclude_fields", "secret"])
def test_any_unknown_public_attribute_rejected(admin: Admin, attr: str) -> None:
    _assert_rejected(admin, f"unknown option '{attr}'.*start with '_'", **{attr: ["email"]})


@pytest.mark.parametrize(
    "alias",
    [
        "column_exclude_list",
        "column_details_exclude_list",
        "column_export_exclude_list",
        "form_excluded_columns",
    ],
)
def test_exclude_aliases_point_to_exclude(admin: Admin, alias: str) -> None:
    _assert_rejected(admin, f"'{alias}'; did you mean 'exclude'", **{alias: ["password_hash"]})


@pytest.mark.parametrize(
    ("option", "hint"),
    [
        ("fields", "exclude and readonly_fields"),
        ("fieldsets", "exclude and readonly_fields"),
        ("form_columns", "exclude and readonly_fields"),
        ("column_details_list", "use exclude"),
        ("column_sortable_list", "sortable"),
        ("list_display_links", "link to the edit view"),
        ("list_editable", "ROADMAP"),
    ],
)
def test_unsupported_django_sqladmin_options(admin: Admin, option: str, hint: str) -> None:
    _assert_rejected(admin, f"option '{option}' is not supported: .*{hint}", **{option: ["email"]})


def test_unknown_option_on_plain_mixin_rejected(admin: Admin) -> None:
    class HideSecrets:
        hidden = ("password_hash",)

    class UserAdmin(HideSecrets, ModelAdmin, model=User):
        pass

    with pytest.raises(ConfigurationError, match="unknown option 'hidden'"):
        admin.register(UserAdmin)


def test_options_from_plain_mixin_are_used(admin: Admin) -> None:
    class HideSecrets:
        exclude: ClassVar[Sequence[str]] = ("password_hash",)

    class UserAdmin(HideSecrets, ModelAdmin, model=User):
        pass

    admin.register(UserAdmin)
    assert "password_hash" not in admin._registry.get("users").fields


@pytest.mark.parametrize("value", ["users", 42])
def test_model_as_plain_attribute_must_be_mapped_class(admin: Admin, value: object) -> None:
    bad = type("BadAdmin", (ModelAdmin,), {"model": value})
    with pytest.raises(ConfigurationError, match="not a mapped SQLAlchemy class"):
        admin.register(bad)


def test_joined_inheritance_primary_key_is_a_field(admin: Admin) -> None:
    admin.register(_admin_class(Engineer, ordering=["-id"]))
    reg = admin._registry.get("engineers")
    assert reg.pk_field == "id"
    assert list(reg.fields) == ["id", "kind", "language"]
    assert reg.fields["id"].table.name == "engineers"
    assert reg.list_display == ("id", "kind", "language")
    assert set(reg.list_display) <= set(reg.fields)


def test_joined_inheritance_primary_key_cannot_be_excluded(admin: Admin) -> None:
    _assert_rejected(admin, "primary key", Engineer, exclude=["id"])


def test_attribute_aliasing_excluded_column_rejected(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="'hash_alias' maps to the same column"):
        admin.register(_admin_class(Account, exclude=["secret_hash"]))


@pytest.mark.parametrize("alias", ["alias_attr", "alias_expr"])
def test_annotated_alias_of_excluded_column_rejected(admin: Admin, alias: str) -> None:
    other = "alias_expr" if alias == "alias_attr" else "alias_attr"
    with pytest.raises(ConfigurationError, match=f"'{alias}' maps to the same column"):
        admin.register(_admin_class(Vault, exclude=["secret_hash", other]))


def test_annotated_aliases_all_excluded_is_accepted(admin: Admin) -> None:
    admin.register(_admin_class(Vault, exclude=["secret_hash", "alias_attr", "alias_expr"]))
    assert set(admin._registry.get("vaults").fields) == {"id", "label"}


@pytest.mark.parametrize("model", [User, Team, Engineer, Account, Gadget, Vault])
def test_fields_are_canonical_table_columns(admin: Admin, model: type[Any]) -> None:
    from faststudio.introspection._columns import mapped_columns  # noqa: PLC0415

    for key, column in mapped_columns(sa_inspect(model)).items():
        assert column.table.c[column.key] is column, key


def test_excluding_all_aliases_is_accepted(admin: Admin) -> None:
    admin.register(_admin_class(Account, exclude=["secret_hash", "hash_alias"]))
    assert set(admin._registry.get("accounts").fields) == {"id", "login"}


def test_foreign_table_column_property_is_not_a_field(admin: Admin) -> None:
    admin.register(_admin_class(Account, exclude=["secret_hash", "hash_alias"]))
    assert "team_name" not in admin._registry.get("accounts").fields
    with pytest.raises(ConfigurationError, match="unknown field 'team_name'"):
        admin.register(_admin_class(Account, identity="acc2", search_fields=["team_name"]))


def test_type_decorators_over_boolean_and_enum_are_filterable(admin: Admin) -> None:
    admin.register(_admin_class(Gadget, list_filter=["flag", "kind"]))
    assert admin._registry.get("gadgets").list_filter == ("flag", "kind")


@pytest.mark.parametrize("field", ["kind", "flag", "variant_label", "dialect_label"])
def test_non_text_or_dialect_dependent_types_not_searchable(admin: Admin, field: str) -> None:
    _assert_rejected(admin, "search_fields.*text", Gadget, search_fields=[field])


@pytest.mark.parametrize("field", ["variant_label", "dialect_label"])
def test_dialect_dependent_types_not_filterable(admin: Admin, field: str) -> None:
    _assert_rejected(admin, "list_filter", Gadget, list_filter=[field])


@pytest.mark.parametrize("bad", ["Us\x00er", "User\u202e", "Us\u200ber", "a\nb"])
@pytest.mark.parametrize("option", ["name", "name_plural"])
def test_display_text_rejects_control_and_format_chars(admin: Admin, option: str, bad: str) -> None:
    _assert_rejected(admin, "control or invisible", **{option: bad})


def test_column_label_rejects_control_chars(admin: Admin) -> None:
    _assert_rejected(admin, "control or invisible", column_labels={"email": "E\u202email"})


def test_markup_in_display_text_is_kept_for_escaping_later(admin: Admin) -> None:
    admin.register(_admin_class(Team, name="</script><b>Team"))
    assert admin._registry.get("teams").name == "</script><b>Team"


def test_sensitive_visible_fields_log_warning(
    admin: Admin, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        admin.register(_admin_class())
    messages = [r.getMessage() for r in caplog.records]
    assert any("'password_hash'" in m and "exclude" in m for m in messages)


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "user_password",
        "pwd",
        "hashed_pw",
        "api_key",
        "apikey_v2",
        "otp_seed",
        "salt",
        "passwordHash",
        "apiKey",
        "userSecret",
    ],
)
def test_sensitive_name_pattern_matches(name: str) -> None:
    from faststudio.introspection._fields import looks_sensitive as _looks_sensitive  # noqa: PLC0415

    assert _looks_sensitive(name)


@pytest.mark.parametrize(
    "name",
    [
        "passenger_count",
        "compass",
        "bypass_cache",
        "hashtag",
        "footprint",
        "tokenizer",
        "salted",
        "passengerCount",
        "hashtagList",
    ],
)
def test_sensitive_name_pattern_ignores_harmless_names(name: str) -> None:
    from faststudio.introspection._fields import looks_sensitive as _looks_sensitive  # noqa: PLC0415

    assert not _looks_sensitive(name)


def test_no_sensitive_warning_when_excluded(admin: Admin, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="faststudio"):
        admin.register(_admin_class(exclude=["password_hash"]))
    assert not any("look sensitive" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [
        ("User", "User"),
        ("BlogPost", "Blog post"),
        ("HTTPLog", "HTTP log"),
        ("UserAPIKey", "User API key"),
        ("Order2Item", "Order2 item"),
        ("E2EUser", "E2E user"),
        ("S3Bucket", "S3 bucket"),
    ],
)
def test_humanize(class_name: str, expected: str) -> None:
    from faststudio.registry import _humanize  # noqa: PLC0415 - private helper

    assert _humanize(class_name) == expected
