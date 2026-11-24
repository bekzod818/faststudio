"""Write API: create, update and delete records (M8, threat model T5)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._paths import API_PREFIX
from faststudio.api._records import detail_row, load_or_404
from faststudio.api.auth import current_user, get_context
from faststudio.api.errors import ApiError, validation_issues
from faststudio.query._write import dependents_statements, exists_statement
from faststudio.registry import RegisteredModel
from faststudio.schemas._dynamic import WriteSchema
from faststudio.schemas.contract import Row, ValidationIssue

logger = logging.getLogger("faststudio.api")
router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])

#: Largest accepted request body (bytes).
MAX_BODY_BYTES = 1024 * 1024


def _invalid(issues: list[ValidationIssue]) -> ApiError:
    return ApiError(422, "validation_error", details=issues)


async def _read_body(request: Request) -> bytes:
    """Read a JSON body of at most MAX_BODY_BYTES, also when no length is declared."""
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise _invalid(
            [ValidationIssue(loc=["body"], msg="Body must be JSON.", type="content_type")]
        )
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise ApiError(413, "payload_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _validated(request: Request, schema: type[WriteSchema]) -> dict[str, Any]:
    """Return only the fields the client sent, validated by the write schema."""
    body = await _read_body(request)
    try:
        model = schema.model_validate_json(body)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        raise _invalid(validation_issues(errors)) from None
    return model.submitted()


async def _check_relations(
    session: AsyncSession, registered: RegisteredModel, values: dict[str, Any]
) -> None:
    issues: list[ValidationIssue] = []
    for name, value in values.items():
        relation = registered.field_specs[name].relation
        if relation is None or value is None:
            continue
        if (await session.execute(exists_statement(relation.target, value))).first() is None:
            issues.append(
                ValidationIssue(
                    loc=[name], msg="Referenced record does not exist.", type="foreign_key"
                )
            )
    if issues:
        raise _invalid(issues)


async def _commit(session: AsyncSession, registered: RegisteredModel, action: str) -> None:
    """Commit, mapping database errors to contract errors without logging values."""
    try:
        await session.commit()
    except StatementError as exc:
        await session.rollback()
        # Database error messages contain SQL and row values: log only the types.
        logger.info(
            "Database error on %s %s: %s (%s)",
            action,
            registered.identity,
            type(exc).__name__,
            type(exc.orig).__name__,
        )
        if isinstance(exc, IntegrityError):
            raise ApiError(409, "conflict") from None
        if isinstance(exc, DataError):
            issue = ValidationIssue(
                loc=["body"], msg="The database rejected a value.", type="database"
            )
            raise _invalid([issue]) from None
        raise ApiError(500, "internal_error") from None


def _require(allowed: bool) -> None:
    if not allowed:
        raise ApiError(403, "forbidden")


@router.post("/models/{identity}/items", status_code=201, response_model=Row)
async def create_item(request: Request, registered: ModelDep, session: DbSession) -> Row:
    """Create a record from the writable fields of the request body."""
    _require(registered.can_create)
    values = await _validated(request, registered.create_schema)
    await _check_relations(session, registered, values)
    obj = registered.model(**values)
    session.add(obj)
    await _commit(session, registered, "create")
    await session.refresh(obj)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.patch("/models/{identity}/items/{pk}", response_model=Row)
async def update_item(request: Request, registered: ModelDep, pk: str, session: DbSession) -> Row:
    """Change the writable fields sent in the body; primary keys never change."""
    _require(registered.can_edit)
    obj = await load_or_404(session, registered, pk)
    values = await _validated(request, registered.update_schema)
    await _check_relations(session, registered, values)
    if values:
        for name, value in values.items():
            setattr(obj, name, value)
        await _commit(session, registered, "update")
        await session.refresh(obj)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.delete("/models/{identity}/items/{pk}", status_code=204)
async def delete_item(registered: ModelDep, pk: str, session: DbSession) -> Response:
    """Delete one record.

    Refused with 409 while an ORM relationship the delete would touch still has
    related rows (one-to-many, many-to-many, or many-to-one with a delete
    cascade), so ORM cascades do not change rows of other models. Rows added
    concurrently between this check and the flush are not covered; database
    foreign-key rules still apply and also give 409.
    """
    _require(registered.can_delete)
    obj = await load_or_404(session, registered, pk)
    for statement in dependents_statements(sa_inspect(registered.model), obj):
        if (await session.execute(statement)).first() is not None:
            raise ApiError(409, "conflict", "Related records still reference this record.")
    await session.delete(obj)
    await _commit(session, registered, "delete")
    return Response(status_code=204)
