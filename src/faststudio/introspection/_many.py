"""Many-to-many relationships over a plain association table (ADR-0010 §1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, Integer, Table, UniqueConstraint
from sqlalchemy.orm import RelationshipDirection, RelationshipProperty
from sqlalchemy.sql.elements import ColumnElement

from faststudio.introspection._types import FieldType, value_type

#: Default and largest allowed number of related keys per field (`many_to_many_limits`).
DEFAULT_MAX_RELATED_ITEMS = 500
MAX_RELATED_ITEMS_LIMIT = 10_000

#: Target primary-key types a many-to-many field can carry on the wire.
_KEY_TYPES: frozenset[FieldType] = frozenset({"integer", "string", "uuid"})


class NotPlainError(Exception):
    """The relationship is not a plain many-to-many; `reason` says why."""

    def __init__(self, reason: str) -> None:
        """Create the error with a human-readable reason."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ManyToManyLink:
    """How a plain many-to-many relationship is stored.

    Reads and writes go straight to `secondary`: `local_fk` points at this
    model's primary key `local_pk`, `remote_fk` at the target's `target_pk`.
    """

    secondary: Table = field(compare=False)
    local_pk: Column[Any] = field(compare=False)
    local_fk: Column[Any] = field(compare=False)
    target_pk: Column[Any] = field(compare=False)
    remote_fk: Column[Any] = field(compare=False)
    target_model: type[Any]
    value_type: FieldType
    viewonly: bool
    #: A primary key or unique constraint covers exactly (local_fk, remote_fk).
    unique_pair: bool


def _single_pair(
    pairs: Sequence[tuple[ColumnElement[Any], ColumnElement[Any]]],
) -> tuple[Column[Any], Column[Any]]:
    if len(pairs) != 1:
        msg = "it joins on more than one column pair"
        raise NotPlainError(msg)
    source, dest = pairs[0]
    if not (isinstance(source, Column) and isinstance(dest, Column)):  # pragma: no cover
        msg = "it joins on SQL expressions, not columns"  # defensive: SQLAlchemy pairs are columns
        raise NotPlainError(msg)
    return source, dest


def _is_equality(join: ColumnElement[bool] | None, a: Column[Any], b: Column[Any]) -> bool:
    """Return True if `join` is exactly `a == b` (either order), with no extra criteria."""
    if join is None:  # pragma: no cover - SQLAlchemy builds both joins for a secondary
        return False
    return bool(join.compare(a == b) or join.compare(b == a))


def _references(fk_column: Column[Any], pk: Column[Any]) -> bool:
    return any(fk.column is pk for fk in fk_column.foreign_keys)


def _has_default(column: Column[Any]) -> bool:
    if column.default is not None or column.server_default is not None:
        return True
    # An integer surrogate key the database numbers itself.
    return bool(
        column.primary_key
        and column.autoincrement in (True, "auto")
        and isinstance(column.type, Integer)
    )


def _covers_pair(secondary: Table, pair: set[Column[Any]]) -> bool:
    """Return True if a primary key, unique constraint or unique index is exactly `pair`."""
    if set(secondary.primary_key.columns) == pair:
        return True
    for constraint in secondary.constraints:
        if isinstance(constraint, UniqueConstraint) and set(constraint.columns) == pair:
            return True
    return any(bool(index.unique) and set(index.columns) == pair for index in secondary.indexes)


def plain_many_to_many(relationship: RelationshipProperty[Any]) -> ManyToManyLink:
    """Describe `relationship` if it is a plain many-to-many.

    Plain means: a `secondary` table whose only foreign keys are one column
    referencing this model's single-column primary key and one referencing the
    target's; every other column has a default; and the join conditions are
    exactly those two equalities (no extra criteria, also for view-only
    relationships), because FastStudio reads and writes the table directly.

    Raises:
        NotPlainError: with the reason otherwise.

    """
    secondary = relationship.secondary
    if relationship.direction is not RelationshipDirection.MANYTOMANY or not isinstance(
        secondary, Table
    ):
        msg = "not a many-to-many relationship"
        raise NotPlainError(msg)
    local_pk, local_fk = _single_pair(relationship.synchronize_pairs)
    target_pk, remote_fk = _single_pair(relationship.secondary_synchronize_pairs or [])
    parent_pk = relationship.parent.primary_key
    target_mapper = relationship.mapper
    if list(parent_pk) != [local_pk] or list(target_mapper.primary_key) != [target_pk]:
        msg = "it must reference the single-column primary keys of both models"
        raise NotPlainError(msg)
    if not (_references(local_fk, local_pk) and _references(remote_fk, target_pk)):
        msg = "its association columns must be foreign keys to both primary keys"
        raise NotPlainError(msg)
    if not (
        _is_equality(relationship.primaryjoin, local_pk, local_fk)
        and _is_equality(relationship.secondaryjoin, target_pk, remote_fk)
    ):
        msg = "it uses a custom join condition (only plain foreign-key equality is supported)"
        raise NotPlainError(msg)
    for column in secondary.columns:
        if column is local_fk or column is remote_fk:
            continue
        if column.foreign_keys:
            msg = f"association table {secondary.name!r} has another foreign key ({column.name!r})"
            raise NotPlainError(msg)
        if not _has_default(column):
            msg = (
                f"association column {column.name!r} has no default "
                f"(table {secondary.name!r}); FastStudio could not insert links"
            )
            raise NotPlainError(msg)
    key_type = value_type(target_pk)
    if key_type not in _KEY_TYPES:
        msg = f"the target primary key type ({key_type}) is not supported"
        raise NotPlainError(msg)
    return ManyToManyLink(
        secondary=secondary,
        local_pk=local_pk,
        local_fk=local_fk,
        target_pk=target_pk,
        remote_fk=remote_fk,
        target_model=target_mapper.class_,
        value_type=key_type,
        viewonly=relationship.viewonly,
        unique_pair=_covers_pair(secondary, {local_fk, remote_fk}),
    )


@dataclass(frozen=True, slots=True)
class ManyToManyField:
    """An opted-in many-to-many field of a registered model (`ModelAdmin.many_to_many`)."""

    name: str
    label: str
    #: Listed in `readonly_fields`, or a view-only relationship.
    readonly: bool
    #: Most related keys read or written at once (`many_to_many_limits`).
    max_items: int
    link: ManyToManyLink
