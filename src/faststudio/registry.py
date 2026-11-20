"""Validation and storage of registered ``ModelAdmin`` classes (private).

The resolved :class:`RegisteredModel` values are the *only* allowlists used
by request handling (search, filter, sort, writes), so validation here fails
closed: anything ambiguous is a ``ConfigurationError`` at startup.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import Column
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoReferenceError
from sqlalchemy.orm import Mapper

from faststudio.exceptions import ConfigurationError
from faststudio.introspection._columns import (
    canonical_column,
    is_filterable,
    is_text,
    mapped_columns,
)
from faststudio.introspection._fields import (
    FieldSpec,
    build_field_spec,
    is_required_column,
    looks_sensitive,
)
from faststudio.introspection._types import FieldType
from faststudio.model_admin import OPTION_NAMES, ModelAdmin

logger = logging.getLogger("faststudio.registry")

_IDENTITY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_ICON = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_ICON_LENGTH = 64
_MAX_NAME_LENGTH = 100
_DEFAULT_LIST_COLUMNS = 4
# Option names from Django Admin / SQLAdmin that users commonly carry over.
_OPTION_ALIASES: dict[str, str] = {
    "list_per_page": "page_size",
    "verbose_name": "name",
    "verbose_name_plural": "name_plural",
    "readonly": "readonly_fields",
    "column_list": "list_display",
    "column_searchable_list": "search_fields",
    "column_filters": "list_filter",
    "column_default_sort": "ordering",
    "column_exclude_list": "exclude",
    "column_details_exclude_list": "exclude",
    "column_export_exclude_list": "exclude",
    "form_excluded_columns": "exclude",
}
# Options FastStudio deliberately does not support, with the closest alternative.
_UNSUPPORTED_OPTIONS: dict[str, str] = {
    "fields": "use exclude and readonly_fields to control the form",
    "fieldsets": "use exclude and readonly_fields to control the form",
    "form_columns": "use exclude and readonly_fields to control the form",
    "column_details_list": "use exclude to hide fields from the detail view",
    "column_sortable_list": "list_display and ordering columns are sortable "
    "(except json/unsupported)",
    "list_display_links": "rows link to the edit view automatically",
    "list_editable": "inline list editing is not available yet (see ROADMAP.md)",
}


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A validated, resolved ``ModelAdmin``. Request code only reads these values."""

    admin_class: type[ModelAdmin]
    model: type[Any]
    identity: str
    name: str
    name_plural: str
    icon: str | None
    pk_field: str
    #: Visible (non-excluded) fields in declaration order -> Column.
    fields: Mapping[str, Column[Any]]
    #: Visible fields in declaration order -> introspected description.
    field_specs: Mapping[str, FieldSpec]
    list_display: tuple[str, ...]
    search_fields: tuple[str, ...]
    list_filter: tuple[str, ...]
    #: (field, descending) pairs.
    ordering: tuple[tuple[str, bool], ...]
    #: Allowlist for client sorting: list_display + ordering, minus json/unsupported.
    sortable_fields: tuple[str, ...]
    readonly_fields: frozenset[str]
    exclude: frozenset[str]
    column_labels: Mapping[str, str]
    page_size: int
    can_create: bool
    can_edit: bool
    can_delete: bool


class Registry:
    """Registered models keyed by identity, in registration order."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._by_identity: dict[str, RegisteredModel] = {}

    def add(self, registered: RegisteredModel) -> None:
        """Store ``registered``; reject duplicate identities and models."""
        label = registered.admin_class.__name__
        if registered.identity in self._by_identity:
            msg = (
                f"{label}: identity {registered.identity!r} is already registered; "
                "set a different identity."
            )
            raise ConfigurationError(msg)
        for existing in self._by_identity.values():
            if existing.model is registered.model:
                msg = (
                    f"{label}: model {registered.model.__name__} is already registered "
                    f"by {existing.admin_class.__name__}."
                )
                raise ConfigurationError(msg)
        self._by_identity[registered.identity] = registered

    def get(self, identity: str) -> RegisteredModel:
        """Return the model registered under ``identity`` or raise ``KeyError``."""
        return self._by_identity[identity]

    def __iter__(self) -> Iterator[RegisteredModel]:
        """Iterate in registration order."""
        return iter(self._by_identity.values())

    def __len__(self) -> int:
        """Return the number of registered models."""
        return len(self._by_identity)


class _Validator:
    """Resolves one ModelAdmin subclass; every error names the class and option."""

    def __init__(
        self, admin_class: type[ModelAdmin], mapper: Mapper[Any], max_page_size: int
    ) -> None:
        self.cls = admin_class
        self.label = admin_class.__name__
        self.mapper = mapper
        self.max_page_size = max_page_size
        self.available: Mapping[str, Column[Any]] = mapped_columns(mapper)
        self.managed: frozenset[int] = _managed_column_ids(mapper)
        self.excluded: frozenset[str] = frozenset()  # set once `exclude` is validated

    def fail(self, message: str) -> ConfigurationError:
        return ConfigurationError(f"{self.label}: {message}")

    # ------------------------------------------------------------------ entry
    def resolve(self) -> RegisteredModel:
        self._check_unknown_options()
        pk_field = self._pk_field()

        exclude = self._fields("exclude")
        if pk_field in exclude:
            raise self.fail(f"exclude: the primary key {pk_field!r} cannot be excluded.")
        self.excluded = frozenset(exclude)
        visible = self._visible_fields()

        list_display = self._fields("list_display", visible_only=True) or self._default_list(
            pk_field, visible
        )
        search_fields = self._fields("search_fields", visible_only=True)
        for field in search_fields:
            if not is_text(visible[field]):
                raise self.fail(
                    f"search_fields: {field!r} is not a string/text column; "
                    "only text columns can be searched."
                )
        list_filter = self._fields("list_filter", visible_only=True)
        for field in list_filter:
            if not is_filterable(visible[field]):
                raise self.fail(
                    f"list_filter: {field!r} must be a boolean or enum column in this version."
                )
        self._warn_sensitive(visible)
        readonly_fields = frozenset(self._fields("readonly_fields", visible_only=True))
        column_labels = self._column_labels()
        field_specs = {
            key: self._field_spec(key, column, column_labels.get(key), key in readonly_fields)
            for key, column in visible.items()
        }
        can_create = self._flag("can_create")
        if can_create:
            self._warn_create_blocked(field_specs)

        name = self._name()
        ordering = self._ordering()
        return RegisteredModel(
            admin_class=self.cls,
            model=self.mapper.class_,
            identity=self._identity(),
            name=name,
            name_plural=self._name_plural(name),
            icon=self._icon(),
            pk_field=pk_field,
            fields=MappingProxyType(visible),
            field_specs=MappingProxyType(field_specs),
            list_display=tuple(list_display),
            search_fields=tuple(search_fields),
            list_filter=tuple(list_filter),
            ordering=ordering,
            sortable_fields=_sortable(list_display, ordering, field_specs),
            readonly_fields=readonly_fields,
            exclude=self.excluded,
            column_labels=column_labels,
            page_size=self._page_size(),
            can_create=can_create,
            can_edit=self._flag("can_edit"),
            can_delete=self._flag("can_delete"),
        )

    # ------------------------------------------------------------------ model
    def _pk_field(self) -> str:
        if len(self.mapper.primary_key) != 1:
            raise self.fail(
                f"{self.mapper.class_.__name__} has a composite primary key, which is not "
                "supported yet (see ROADMAP.md)."
            )
        pk_field = self.mapper.get_property_by_column(self.mapper.primary_key[0]).key
        if pk_field not in self.available:
            raise self.fail(  # pragma: no cover - defensive; mapped_columns keeps own pk columns
                f"primary key attribute {pk_field!r} could not be resolved to a column."
            )
        return pk_field

    def _visible_fields(self) -> dict[str, Column[Any]]:
        """Non-excluded fields; reject attributes aliasing an excluded column."""
        excluded_columns = {id(self.available[name]): name for name in self.excluded}
        visible: dict[str, Column[Any]] = {}
        for key, column in self.available.items():
            if key in self.excluded:
                continue
            original = excluded_columns.get(id(column))
            if original is not None:
                raise self.fail(
                    f"exclude: attribute {key!r} maps to the same column as excluded field "
                    f"{original!r}; exclude it too."
                )
            visible[key] = column
        return visible

    def _siblings(self, key: str, column: Column[Any]) -> list[Column[Any]]:
        """Other columns of the same attribute (joined-inheritance primary keys)."""
        prop = self.mapper.get_property(key)
        others = [
            canonical_column(c) for c in getattr(prop, "columns", ()) if isinstance(c, Column)
        ]
        return [c for c in others if c is not column]

    def _is_managed(self, column: Column[Any], siblings: Sequence[Column[Any]]) -> bool:
        return any(id(c) in self.managed for c in (column, *siblings))

    def _field_spec(
        self, key: str, column: Column[Any], label: str | None, readonly: bool
    ) -> FieldSpec:
        siblings = self._siblings(key, column)
        try:
            return build_field_spec(
                key,
                column,
                label=label,
                readonly=readonly,
                siblings=siblings,
                managed=self._is_managed(column, siblings),
            )
        except NoReferenceError as exc:
            raise self.fail(
                f"field {key!r} has a foreign key that cannot be resolved: {exc}"
            ) from exc

    def _warn_create_blocked(self, field_specs: Mapping[str, FieldSpec]) -> None:
        """Warn if the database needs a value that no create request can supply."""
        blocked: list[str] = []
        for key, column in self.available.items():
            siblings = self._siblings(key, column)
            if not is_required_column(column, siblings, managed=self._is_managed(column, siblings)):
                continue
            spec = field_specs.get(key)
            if spec is None or spec.readonly:
                blocked.append(key)
        if blocked:
            logger.warning(
                "%s: creating rows will fail because required field(s) %s are excluded or "
                "readonly; set can_create = False or give them a default.",
                self.label,
                ", ".join(repr(k) for k in blocked),
            )

    def _warn_sensitive(self, visible: Mapping[str, Column[Any]]) -> None:
        exposed = [key for key in visible if looks_sensitive(key)]
        if exposed:
            logger.warning(
                "%s: field(s) %s look sensitive but are not excluded; add them to "
                "`exclude` unless they are safe to show and edit.",
                self.label,
                ", ".join(repr(k) for k in exposed),
            )

    # ------------------------------------------------------------------ options
    def _check_unknown_options(self) -> None:
        known = sorted(OPTION_NAMES)
        for klass in self.cls.__mro__:
            if klass in (ModelAdmin, object):
                continue
            for attr, value in vars(klass).items():
                if attr.startswith("_") or attr in OPTION_NAMES:
                    continue
                if callable(value) or isinstance(value, (classmethod, staticmethod, property)):
                    continue
                self._reject_unknown(attr, known)

    def _reject_unknown(self, attr: str, known: list[str]) -> None:
        if attr in _UNSUPPORTED_OPTIONS:
            raise self.fail(f"option {attr!r} is not supported: {_UNSUPPORTED_OPTIONS[attr]}.")
        if attr in _OPTION_ALIASES:
            raise self.fail(f"unknown option {attr!r}; did you mean {_OPTION_ALIASES[attr]!r}?")
        hint = next(iter(difflib.get_close_matches(attr, known, n=1, cutoff=0.8)), None)
        suggestion = f" Did you mean {hint!r}?" if hint else ""
        raise self.fail(
            f"unknown option {attr!r}.{suggestion} Custom class attributes must start "
            "with '_' so misspelled options never fail silently."
        )

    def _overridden(self, option: str) -> bool:
        return any(
            option in vars(klass) for klass in self.cls.__mro__ if klass not in (ModelAdmin, object)
        )

    def _sequence(self, option: str) -> Sequence[object]:
        value: object = getattr(self.cls, option)
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise self.fail(f"{option} must be a list or tuple of field names.")
        return value

    def _field_name(self, option: str, entry: object) -> str:
        if not isinstance(entry, str):
            raise self.fail(f"{option}: entries must be field names (str), got {entry!r}.")
        if entry not in self.available:
            raise self.fail(
                f"{option}: unknown field {entry!r}. Available fields: {', '.join(self.available)}."
            )
        return entry

    def _fields(self, option: str, *, visible_only: bool = False) -> list[str]:
        result: list[str] = []
        for entry in self._sequence(option):
            field = self._field_name(option, entry)
            if field in result:
                raise self.fail(f"{option}: duplicate field {field!r}.")
            if visible_only and field in self.excluded:
                raise self.fail(f"{option}: {field!r} is excluded and cannot be used here.")
            result.append(field)
        return result

    def _default_list(self, pk_field: str, visible: Mapping[str, Column[Any]]) -> list[str]:
        others = [key for key in visible if key != pk_field]
        return [pk_field, *others[:_DEFAULT_LIST_COLUMNS]]

    def _ordering(self) -> tuple[tuple[str, bool], ...]:
        result: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for entry in self._sequence("ordering"):
            if not isinstance(entry, str) or not entry:
                raise self.fail(f"ordering: invalid entry {entry!r}; use 'field' or '-field'.")
            descending = entry.startswith("-")
            field = self._field_name("ordering", entry[1:] if descending else entry)
            if field in self.excluded:
                raise self.fail(f"ordering: {field!r} is excluded and cannot be used here.")
            if field in seen:
                raise self.fail(f"ordering: duplicate field {field!r}.")
            seen.add(field)
            result.append((field, descending))
        return tuple(result)

    def _identity(self) -> str:
        value: object = self.cls.identity
        if value is None:
            value = getattr(self.mapper.local_table, "name", None)
        if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
            raise self.fail(
                f"identity {value!r} is invalid: use 1-64 lowercase letters, digits, '_' or '-' "
                "(set `identity = ...` explicitly if the table name does not fit)."
            )
        return value

    def _text(self, option: str, value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_NAME_LENGTH:
            raise self.fail(
                f"{option} must be a non-empty str of at most {_MAX_NAME_LENGTH} chars."
            )
        if any(unicodedata.category(ch) in {"Cc", "Cf"} for ch in value):
            raise self.fail(
                f"{option} must not contain control or invisible formatting characters."
            )
        return value.strip()

    def _name(self) -> str:
        if self.cls.name is None:
            return _humanize(self.mapper.class_.__name__)
        return self._text("name", self.cls.name)

    def _name_plural(self, name: str) -> str:
        if self.cls.name_plural is None:
            return _pluralize(name)
        return self._text("name_plural", self.cls.name_plural)

    def _icon(self) -> str | None:
        icon: object = self.cls.icon
        if icon is None:
            return None
        if not isinstance(icon, str) or len(icon) > _MAX_ICON_LENGTH or not _ICON.fullmatch(icon):
            raise self.fail(f"icon {icon!r} must be a lucide icon name such as 'users'.")
        return icon

    def _column_labels(self) -> Mapping[str, str]:
        labels: object = self.cls.column_labels
        if not isinstance(labels, Mapping):
            raise self.fail("column_labels must be a mapping of field name to label.")
        result: dict[str, str] = {}
        for key, label in labels.items():
            field = self._field_name("column_labels", key)
            if field in self.excluded:
                raise self.fail(f"column_labels: {field!r} is excluded and cannot be used here.")
            result[field] = self._text(f"column_labels[{field!r}]", label)
        return MappingProxyType(result)

    def _page_size(self) -> int:
        size: object = self.cls.page_size
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise self.fail("page_size must be a positive int.")
        if size > self.max_page_size:
            if not self._overridden("page_size"):
                return self.max_page_size  # the built-in default adapts to a smaller cap
            raise self.fail(f"page_size {size} exceeds Admin(max_page_size={self.max_page_size}).")
        return size

    def _flag(self, option: str) -> bool:
        value: object = getattr(self.cls, option)
        if not isinstance(value, bool):
            raise self.fail(f"{option} must be True or False.")
        return value


def resolve_model_admin(admin_class: object, *, max_page_size: int) -> RegisteredModel:
    """Validate ``admin_class`` and return its resolved configuration."""
    if (
        not isinstance(admin_class, type)
        or not issubclass(admin_class, ModelAdmin)
        or admin_class is ModelAdmin
    ):
        msg = f"register() expects a ModelAdmin subclass, got {admin_class!r}."
        raise ConfigurationError(msg)
    label = admin_class.__name__
    model: object = getattr(admin_class, "model", None)
    if model is None:
        msg = f"{label}: no model; declare it as `class X(ModelAdmin, model=MyModel)`."
        raise ConfigurationError(msg)
    mapper: object = sa_inspect(model, raiseerr=False) if isinstance(model, type) else None
    if not isinstance(mapper, Mapper):
        msg = f"{label}: {model!r} is not a mapped SQLAlchemy class."
        raise ConfigurationError(msg)
    return _Validator(admin_class, mapper, max_page_size).resolve()


# Values the database cannot order meaningfully (or portably).
_UNSORTABLE: frozenset[FieldType] = frozenset({"json", "unsupported"})


def _sortable(
    list_display: Sequence[str],
    ordering: Sequence[tuple[str, bool]],
    field_specs: Mapping[str, FieldSpec],
) -> tuple[str, ...]:
    result: list[str] = []
    for field in (*list_display, *(f for f, _ in ordering)):
        if field not in result and field_specs[field].type not in _UNSORTABLE:
            result.append(field)
    return tuple(result)


def _managed_column_ids(mapper: Mapper[Any]) -> frozenset[int]:
    """Columns the mapper maintains itself: polymorphic discriminators and version ids."""
    ids: set[int] = set()
    for current in mapper.iterate_to_root():
        for column in (current.polymorphic_on, current.version_id_col):
            if isinstance(column, Column):
                ids.add(id(canonical_column(column)))
    return frozenset(ids)


def _humanize(class_name: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", class_name).split()
    return " ".join([words[0], *(w if w.isupper() else w.lower() for w in words[1:])])


def _pluralize(name: str) -> str:
    lower = name.lower()
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return name[:-1] + "ies"
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"
