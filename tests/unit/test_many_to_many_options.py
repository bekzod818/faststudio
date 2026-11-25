"""ModelAdmin.many_to_many and many_to_many_limits validation (ADR-0010, M15)."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from faststudio import Admin, ConfigurationError, ModelAdmin
from faststudio.introspection._many import DEFAULT_MAX_RELATED_ITEMS, MAX_RELATED_ITEMS_LIMIT
from tests._stubs import StubAuthBackend
from tests.factories.models import Article, Parent, Person, Post


@pytest.fixture
def admin(
    app: FastAPI, engine: AsyncEngine, auth_backend: StubAuthBackend, secret_key: str
) -> Admin:
    return Admin(app, engine=engine, auth_backend=auth_backend, secret_key=secret_key)


def _admin_class(model: type[Any] = Post, /, **options: Any) -> type[ModelAdmin]:
    return type(f"{model.__name__}Admin", (ModelAdmin,), dict(options), model=model)


def _rejected(admin: Admin, match: str, model: type[Any] = Post, /, **options: Any) -> None:
    with pytest.raises(ConfigurationError, match=match):
        admin.register(_admin_class(model, **options))


# --------------------------------------------------------------------------- accepted


def test_defaults_expose_no_many_to_many(admin: Admin) -> None:
    admin.register(_admin_class())
    reg = admin._registry.get("posts")
    assert dict(reg.many_to_many) == {}
    assert "tags" not in reg.field_specs


def test_opt_in(admin: Admin) -> None:
    admin.register(_admin_class(many_to_many=("tags",)))
    field = admin._registry.get("posts").many_to_many["tags"]
    assert (field.name, field.label, field.readonly) == ("tags", "Tags", False)
    assert field.max_items == DEFAULT_MAX_RELATED_ITEMS == 500
    assert field.link.secondary.name == "post_tags"


def test_limits_labels_and_readonly(admin: Admin) -> None:
    admin.register(
        _admin_class(
            many_to_many=["tags"],
            many_to_many_limits=MappingProxyType({"tags": MAX_RELATED_ITEMS_LIMIT}),
            column_labels={"tags": "Topics"},
            readonly_fields=("tags",),
        )
    )
    field = admin._registry.get("posts").many_to_many["tags"]
    assert (field.label, field.readonly, field.max_items) == ("Topics", True, 10_000)


def test_self_referential_and_viewonly(admin: Admin) -> None:
    admin.register(_admin_class(Person, many_to_many=("follows",)))
    admin.register(_admin_class(Article, many_to_many=("topics", "seen_topics")))
    assert admin._registry.get("people").many_to_many["follows"].readonly is False
    assert admin._registry.get("articles").many_to_many["seen_topics"].readonly is True


def test_missing_unique_pair_warns(admin: Admin, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="faststudio"):
        admin.register(_admin_class(Article, many_to_many=("loose_topics",)))
    assert "article_loose_topics" in caplog.text
    assert "unique" in caplog.text


def test_unique_pair_does_not_warn(admin: Admin, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="faststudio"):
        admin.register(_admin_class(many_to_many=("tags",)))
    assert "post_tags" not in caplog.text


# --------------------------------------------------------------------------- rejected


@pytest.mark.parametrize(
    ("model", "options", "match"),
    [
        (Post, {"many_to_many": "tags"}, "many_to_many must be a list or tuple"),
        (Post, {"many_to_many": ("tags", "tags")}, "many_to_many: duplicate field 'tags'"),
        (Post, {"many_to_many": (1,)}, "many_to_many: entries must be relationship names"),
        (Post, {"many_to_many": ("nope",)}, r"many_to_many: unknown relationship 'nope'.*tags"),
        (Post, {"many_to_many": ("title",)}, "many_to_many: 'title' is a column"),
        (Parent, {"many_to_many": ("children",)}, "'children' is not a plain many-to-many"),
        (
            Article,
            {"many_to_many": ("weighted_topics",)},
            "'weighted_topics' is not a plain many-to-many.*'weight' has no default",
        ),
        (Article, {"many_to_many": ("active_topics",)}, "custom join condition"),
        (Article, {"many_to_many": ("filtered_topics",)}, "custom join condition"),
    ],
)
def test_many_to_many_rejected(
    admin: Admin, model: type[Any], options: dict[str, Any], match: str
) -> None:
    _rejected(admin, match, model, **options)


@pytest.mark.parametrize(
    ("limits", "match"),
    [
        (["tags"], "many_to_many_limits must be a mapping"),
        ({"tags": 0}, r"many_to_many_limits\['tags'\] must be an int between 1 and 10000"),
        ({"tags": -1}, "between 1 and 10000"),
        ({"tags": 10_001}, "between 1 and 10000"),
        ({"tags": True}, "between 1 and 10000"),
        ({"tags": 10.0}, "between 1 and 10000"),
        ({"tags": "10"}, "between 1 and 10000"),
        ({"other": 5}, "many_to_many_limits: 'other' is not listed in many_to_many"),
        ({1: 5}, "many_to_many_limits: 1 is not listed in many_to_many"),
    ],
)
def test_limits_rejected(admin: Admin, limits: object, match: str) -> None:
    _rejected(admin, match, many_to_many=("tags",), many_to_many_limits=limits)


def test_unknown_relationship_lists_only_plain_ones(admin: Admin) -> None:
    with pytest.raises(ConfigurationError, match="nope") as caught:
        admin.register(_admin_class(Article, many_to_many=("nope",)))
    message = str(caught.value)
    assert "topics, loose_topics" in message
    assert "weighted_topics" not in message  # not plain
    assert "active_topics" not in message


def test_limits_without_many_to_many_rejected(admin: Admin) -> None:
    _rejected(admin, "'tags' is not listed in many_to_many", many_to_many_limits={"tags": 5})


@pytest.mark.parametrize("option", ["list_display", "search_fields", "list_filter", "ordering"])
def test_many_to_many_field_cannot_be_listed_searched_filtered_or_sorted(
    admin: Admin, option: str
) -> None:
    _rejected(
        admin,
        f"{option}: 'tags' is a many-to-many field; many-to-many fields cannot be listed, "
        "searched, filtered or sorted in this version",
        many_to_many=("tags",),
        **{option: ("tags",)},
    )


def test_relationship_in_column_option_without_opt_in(admin: Admin) -> None:
    _rejected(admin, "list_display: 'tags' is a relationship", list_display=("tags",))


def test_exclude_rejects_relationships(admin: Admin) -> None:
    _rejected(
        admin,
        "exclude: 'tags' is a relationship, not a column; leave it out of many_to_many",
        exclude=("tags",),
    )


def test_readonly_and_labels_reject_relationships_that_are_not_opted_in(admin: Admin) -> None:
    _rejected(admin, "readonly_fields: 'tags' is a relationship", readonly_fields=("tags",))
    _rejected(admin, "column_labels: 'tags' is a relationship", column_labels={"tags": "T"})
