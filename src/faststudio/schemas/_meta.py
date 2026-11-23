"""Build contract ``ModelMeta`` objects from registered models."""

from __future__ import annotations

from faststudio.introspection._fields import FieldSpec, JsonValue, Relation
from faststudio.registry import RegisteredModel, Registry
from faststudio.schemas.contract import (
    MAX_SAFE_INTEGER,
    ChoiceMeta,
    FieldMeta,
    FilterMeta,
    ModelMeta,
    PermissionsMeta,
    RelationMeta,
)


def build_models_meta(registry: Registry) -> list[ModelMeta]:
    """Describe every registered model, in registration order."""
    return [build_model_meta(registered, registry) for registered in registry]


def build_model_meta(registered: RegisteredModel, registry: Registry) -> ModelMeta:
    """Describe one registered model for the SPA."""
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
        permissions=PermissionsMeta(
            create=registered.can_create, edit=registered.can_edit, delete=registered.can_delete
        ),
        fields=[_field_meta(spec, registry) for spec in specs.values()],
    )


def _choices(spec: FieldSpec) -> list[ChoiceMeta] | None:
    if spec.choices is None:
        return None
    return [ChoiceMeta(value=c.value, label=c.label) for c in spec.choices]


def _filter_meta(field: str, spec: FieldSpec) -> FilterMeta:
    if spec.type == "boolean":
        return FilterMeta(field=field, kind="boolean", choices=[])
    return FilterMeta(field=field, kind="choice", choices=_choices(spec) or [])


def _relation_meta(relation: Relation, registry: Registry) -> RelationMeta:
    """Resolve the target model now: it may have been registered after the source."""
    target = registry.target_of(relation.target)
    if target is None:
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


def _field_meta(spec: FieldSpec, registry: Registry) -> FieldMeta:
    return FieldMeta(
        name=spec.name,
        label=spec.label,
        type=spec.type,
        nullable=spec.nullable,
        required=spec.required,
        readonly=spec.readonly,
        create_only=spec.create_only,
        primary_key=spec.primary_key,
        default=_safe_default(spec.default),
        has_default=spec.has_default,
        max_length=spec.max_length,
        min_value=_safe_int(spec.min_value),
        max_value=_safe_int(spec.max_value),
        choices=_choices(spec),
        relation=_relation_meta(spec.relation, registry) if spec.relation else None,
        timezone=spec.timezone,
        precision=spec.precision,
        scale=spec.scale,
        help_text=spec.help_text,
    )
