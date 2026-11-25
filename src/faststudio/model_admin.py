"""Declarative ``ModelAdmin`` options."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, ClassVar, cast

from faststudio.exceptions import ConfigurationError


class ModelAdmin:
    """Declares how one SQLAlchemy model appears in FastStudio.

    Subclass with the model as a class keyword and register it::

        @admin.register
        class UserAdmin(ModelAdmin, model=User):
            list_display = ["id", "email", "is_active"]
            search_fields = ["email"]
            list_filter = ["is_active"]

    Options are class attributes validated by :meth:`faststudio.Admin.register`;
    any mistake raises :class:`~faststudio.ConfigurationError` at startup.
    Unknown public attributes are rejected (so a misspelled ``exclude`` can
    never silently expose a column); name custom attributes with a leading
    underscore. Methods are allowed. Intermediate base classes may omit
    ``model`` to share options.
    """

    model: ClassVar[type[Any]]
    #: URL slug used in API paths. Defaults to the table name.
    identity: ClassVar[str | None] = None
    #: Singular display name. Defaults to the humanized model class name.
    name: ClassVar[str | None] = None
    #: Plural display name. Defaults to ``name`` with a simple English plural.
    name_plural: ClassVar[str | None] = None
    #: A lucide icon name such as ``"users"``.
    icon: ClassVar[str | None] = None
    #: Columns shown in the list view. Defaults to the primary key and the next 4 columns.
    list_display: ClassVar[Sequence[str]] = ()
    #: String/text columns searched (case-insensitive contains) by the search box.
    search_fields: ClassVar[Sequence[str]] = ()
    #: Boolean or enum columns offered as list filters.
    list_filter: ClassVar[Sequence[str]] = ()
    #: Default sort, e.g. ``["-created_at", "email"]``.
    ordering: ClassVar[Sequence[str]] = ()
    #: Rows per list page; must not exceed ``Admin(max_page_size=...)``.
    page_size: ClassVar[int] = 25
    #: Shown but never writable.
    readonly_fields: ClassVar[Sequence[str]] = ()
    #: Never shown, searched, filtered, sorted or writable. Always exclude secrets.
    exclude: ClassVar[Sequence[str]] = ()
    #: Display labels per field.
    column_labels: ClassVar[Mapping[str, str]] = MappingProxyType({})
    #: Many-to-many relationships shown as editable fields, e.g. ``("tags",)``.
    #: Each must be a ``relationship()`` over a plain association table (two
    #: foreign keys to the single-column primary keys, no custom join
    #: condition). Unlisted relationships stay invisible.
    many_to_many: ClassVar[Sequence[str]] = ()
    #: Most related keys per many-to-many field, e.g. ``{"tags": 2000}``.
    #: Default 500; 1 to 10 000. Keys must be listed in ``many_to_many``.
    many_to_many_limits: ClassVar[Mapping[str, int]] = MappingProxyType({})
    can_create: ClassVar[bool] = True
    can_edit: ClassVar[bool] = True
    can_delete: ClassVar[bool] = True

    def __init_subclass__(cls, *, model: type[Any] | None = None, **kwargs: object) -> None:
        """Capture the ``model=`` class keyword."""
        super().__init_subclass__(**kwargs)
        if model is not None:
            if not isinstance(cast("object", model), type):  # untyped callers
                msg = f"{cls.__name__}: model= must be a mapped class, got {model!r}."
                raise ConfigurationError(msg)
            cls.model = model


OPTION_NAMES: frozenset[str] = frozenset(
    {
        "model",
        "identity",
        "name",
        "name_plural",
        "icon",
        "list_display",
        "search_fields",
        "list_filter",
        "ordering",
        "page_size",
        "readonly_fields",
        "exclude",
        "column_labels",
        "many_to_many",
        "many_to_many_limits",
        "can_create",
        "can_edit",
        "can_delete",
    }
)
