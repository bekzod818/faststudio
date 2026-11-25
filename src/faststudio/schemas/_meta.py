"""Build contract ``ModelMeta`` objects from registered models."""

from __future__ import annotations

from collections.abc import Mapping

from faststudio.auth.guard import AccountGuard
from faststudio.introspection._fields import FieldSpec, JsonValue, Relation
from faststudio.introspection._many import ManyToManyField
from faststudio.registry import RegisteredModel, Registry
from faststudio.schemas.contract import (
    MAX_SAFE_INTEGER,
    AccountMeta,
    ChoiceMeta,
    FieldMeta,
    FilterMeta,
    ModelMeta,
    PermissionsMeta,
    RelationMeta,
)


def build_models_meta(
    registry: Registry,
    *,
    guard: AccountGuard | None = None,
    permissions: Mapping[str, PermissionsMeta] | None = None,
    set_password: bool = False,
) -> list[ModelMeta]:
    """Describe the registered models the admin may view, in registration order.

    `permissions` maps each viewable identity to the admin's permissions on it
    (ADR-0011 §5); ``None`` describes every model with its static flags.
    """
    visible = None if permissions is None else frozenset(permissions)
    return [
        build_model_meta(
            registered,
            registry,
            guard=guard,
            permissions=None if permissions is None else permissions[registered.identity],
            visible=visible,
            set_password=set_password,
        )
        for registered in registry
        if visible is None or registered.identity in visible
    ]


def _account_meta(
    registered: RegisteredModel, guard: AccountGuard | None, *, set_password: bool
) -> AccountMeta | None:
    """List the guard's protected fields the form can show and send (ADR-0009)."""
    if guard is None or not guard.guards(registered.model):
        return None
    specs = registered.field_specs
    protected = [
        name
        for name in guard.protected_fields(registered.model)
        if name in specs and not specs[name].readonly
    ]
    flag = guard.admin_flag(registered.model)
    return AccountMeta(
        protected_fields=protected,
        admin_flag=flag
        if flag is not None and flag in specs and not specs[flag].readonly
        else None,
        set_password=set_password,
    )


def build_model_meta(
    registered: RegisteredModel,
    registry: Registry,
    *,
    guard: AccountGuard | None = None,
    permissions: PermissionsMeta | None = None,
    visible: frozenset[str] | None = None,
    set_password: bool = False,
) -> ModelMeta:
    """Describe one registered model for the SPA.

    Relations to models outside `visible` have no target and are readonly for
    this admin (A1): the existence check could otherwise probe a hidden model.
    """
    specs = registered.field_specs
    return ModelMeta(
        identity=registered.identity,
        name=registered.name,
        name_plural=registered.name_plural,
        icon=registered.icon,
        pk_field=registered.pk_field,
        list_display=list(registered.list_display),
        search_fields=list(registered.search_fields),
        list_filter=[_filter_meta(field, specs[field]) for field in registered.list_filter],
        ordering=[f"-{f}" if desc else f for f, desc in registered.ordering],
        sortable_fields=list(registered.sortable_fields),
        page_size=registered.page_size,
        permissions=permissions
        or PermissionsMeta(
            view=True,
            create=registered.can_create,
            edit=registered.can_edit,
            delete=registered.can_delete,
        ),
        fields=[
            *(_field_meta(spec, registry, visible) for spec in specs.values()),
            *(_many_meta(field, registry, visible) for field in registered.many_to_many.values()),
        ],
        account=_account_meta(
            registered,
            guard,
            set_password=set_password
            and (permissions.edit if permissions is not None else registered.can_edit),
        ),
    )


def _choices(spec: FieldSpec) -> list[ChoiceMeta] | None:
    if spec.choices is None:
        return None
    return [ChoiceMeta(value=c.value, label=c.label) for c in spec.choices]


def _filter_meta(field: str, spec: FieldSpec) -> FilterMeta:
    if spec.type == "boolean":
        return FilterMeta(field=field, kind="boolean", choices=[])
    return FilterMeta(field=field, kind="choice", choices=_choices(spec) or [])


def hidden_target(relation: Relation, registry: Registry, visible: frozenset[str] | None) -> bool:
    """Return True if the relation's target is registered but not viewable."""
    target = registry.target_of(relation.target)
    return target is not None and visible is not None and target.identity not in visible


def _relation_meta(
    relation: Relation, registry: Registry, visible: frozenset[str] | None
) -> RelationMeta:
    """Resolve the target model now: it may have been registered after the source."""
    target = registry.target_of(relation.target)
    if target is None or hidden_target(relation, registry, visible):
        return RelationMeta(target_identity=None, target_field=None, value_type=relation.value_type)
    return RelationMeta(
        target_identity=target.identity,
        target_field=target.pk_field,
        value_type=relation.value_type,
    )


def _safe_default(value: JsonValue) -> JsonValue:
    """Integer defaults JavaScript cannot represent exactly are not published."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_SAFE_INTEGER:
        return None
    return value


def _safe_int(value: int | None) -> int | None:
    return value if value is not None and abs(value) <= MAX_SAFE_INTEGER else None


def _field_meta(spec: FieldSpec, registry: Registry, visible: frozenset[str] | None) -> FieldMeta:
    hidden = spec.relation is not None and hidden_target(spec.relation, registry, visible)
    return FieldMeta(
        name=spec.name,
        label=spec.label,
        type=spec.type,
        nullable=spec.nullable,
        required=spec.required,
        readonly=spec.readonly or hidden,
        create_only=spec.create_only,
        primary_key=spec.primary_key,
        default=_safe_default(spec.default),
        has_default=spec.has_default,
        max_length=spec.max_length,
        min_value=_safe_int(spec.min_value),
        max_value=_safe_int(spec.max_value),
        choices=_choices(spec),
        relation=_relation_meta(spec.relation, registry, visible) if spec.relation else None,
        timezone=spec.timezone,
        precision=spec.precision,
        scale=spec.scale,
        help_text=spec.help_text,
        max_items=None,
    )


def _many_meta(
    field: ManyToManyField, registry: Registry, visible: frozenset[str] | None
) -> FieldMeta:
    """Describe an opted-in many-to-many field (ADR-0010): a list of target keys."""
    link = field.link
    relation = Relation(link.target_pk, link.value_type)
    return FieldMeta(
        name=field.name,
        label=field.label,
        type="many_to_many",
        nullable=False,
        required=False,
        readonly=field.readonly or hidden_target(relation, registry, visible),
        create_only=False,
        primary_key=False,
        default=[],
        has_default=True,
        max_length=None,
        min_value=None,
        max_value=None,
        choices=None,
        relation=_relation_meta(relation, registry, visible),
        timezone=None,
        precision=None,
        scale=None,
        help_text=None,
        max_items=field.max_items,
    )
