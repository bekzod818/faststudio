"""Statements used by the write API (foreign-key and dependent-row checks)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Select, literal, select
from sqlalchemy.orm import Mapper, RelationshipDirection, with_parent


def exists_statement(column: Column[Any], value: object) -> Select[Any]:
    """`SELECT 1` if a row with `column == value` exists (the database FK's own check)."""
    return select(literal(1)).where(column == value).limit(1)


def _points_nowhere(mapper: Mapper[Any], relationship: Any, obj: object) -> bool:  # noqa: ANN401 - a RelationshipProperty
    """Return True if every foreign-key column of a many-to-one relationship is NULL."""
    return all(
        getattr(obj, mapper.get_property_by_column(column).key) is None
        for column in relationship.local_columns
    )


def dependents_statements(mapper: Mapper[Any], obj: object) -> list[Select[Any]]:
    """`SELECT 1` per relationship whose related rows a delete would touch.

    That is every one-to-many / many-to-many relationship (the ORM would null
    or cascade-delete their rows) and every many-to-one relationship with a
    `delete` cascade (the ORM would delete the referenced row). The delete is
    refused while any of these has related rows.
    """
    statements: list[Select[Any]] = []
    for relationship in mapper.relationships:
        cascades_delete = "delete" in relationship.cascade
        if relationship.direction is RelationshipDirection.MANYTOONE and (
            not cascades_delete or _points_nowhere(mapper, relationship, obj)
        ):
            continue
        related = relationship.mapper.class_
        attribute = getattr(mapper.class_, relationship.key)
        statements.append(
            select(literal(1)).select_from(related).where(with_parent(obj, attribute)).limit(1)
        )
    return statements
