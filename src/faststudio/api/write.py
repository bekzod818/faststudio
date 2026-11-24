"""Write API: create, update and delete records (M8, threat model T5)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from faststudio.api._db_errors import is_lock_conflict
from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._paths import API_PREFIX
from faststudio.api._records import detail_row, load_or_404
from faststudio.api.auth import CurrentUser, current_user, get_context
from faststudio.api.errors import ApiError, validation_issues
from faststudio.auth._guard import (
    AccountGuard,
    PostWriteCheck,
    WriteIntent,
    WriteRefused,
)
from faststudio.auth.backend import AuthenticatedUser
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


@asynccontextmanager
async def _writing(
    session: AsyncSession, registered: RegisteredModel, action: str
) -> AsyncIterator[None]:
    """Run a write and commit it, mapping failures to contract errors.

    The body applies the change and flushes it, so database errors and guard
    refusals both surface here, before the commit. Nothing is logged with
    values: database error messages contain SQL and row data.
    """
    try:
        yield
        await session.commit()
    except ApiError:
        await session.rollback()
        raise
    except WriteRefused as exc:
        await session.rollback()
        raise ApiError(409, exc.code, exc.message) from None
    except StaleDataError:
        # The row was deleted by a concurrent request after it was loaded.
        await session.rollback()
        logger.info("Concurrent change on %s %s", action, registered.identity)
        raise ApiError(409, "conflict") from None
    except StatementError as exc:
        await session.rollback()
        logger.info(
            "Database error on %s %s: %s (%s)",
            action,
            registered.identity,
            type(exc).__name__,
            type(exc.orig).__name__,
        )
        if isinstance(exc, IntegrityError) or is_lock_conflict(exc):
            # Lock races (another request wrote the same rows first) are
            # conflicts too, never server errors.
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


async def _guard(
    request: Request, session: AsyncSession, user: AuthenticatedUser, intent: WriteIntent
) -> PostWriteCheck | None:
    """Ask the auth backend's account guard about this write (ADR-0009)."""
    backend = get_context(request).auth_backend
    if not isinstance(backend, AccountGuard) or not backend.guards(intent.model):
        return None
    return await backend.before_write(session, user, intent)


@router.post("/models/{identity}/items", status_code=201, response_model=Row)
async def create_item(request: Request, registered: ModelDep, session: DbSession) -> Row:
    """Create a record from the writable fields of the request body."""
    _require(registered.can_create)
    values = await _validated(request, registered.create_schema)
    await _check_relations(session, registered, values)
    obj = registered.model(**values)
    async with _writing(session, registered, "create"):
        session.add(obj)
        await session.flush()
    await session.refresh(obj)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.patch("/models/{identity}/items/{pk}", response_model=Row)
async def update_item(
    request: Request, registered: ModelDep, pk: str, session: DbSession, user: CurrentUser
) -> Row:
    """Change the writable fields sent in the body; primary keys never change."""
    _require(registered.can_edit)
    obj = await load_or_404(session, registered, pk)
    values = await _validated(request, registered.update_schema)
    await _check_relations(session, registered, values)
    if values:
        async with _writing(session, registered, "update"):
            intent = WriteIntent(model=registered.model, obj=obj, action="update", changes=values)
            check = await _guard(request, session, user, intent)
            for name, value in values.items():
                setattr(obj, name, value)
            await session.flush()
            if check is not None:
                await check()
        await session.refresh(obj)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.delete("/models/{identity}/items/{pk}", status_code=204)
async def delete_item(
    request: Request, registered: ModelDep, pk: str, session: DbSession, user: CurrentUser
) -> Response:
    """Delete one record.

    Refused with 409 while an ORM relationship the delete would touch still has
    related rows (one-to-many, many-to-many, or many-to-one with a delete
    cascade), so ORM cascades do not change rows of other models. Rows added
    concurrently between this check and the flush are not covered; database
    foreign-key rules still apply and also give 409.
    """
    _require(registered.can_delete)
    obj = await load_or_404(session, registered, pk)
    async with _writing(session, registered, "delete"):
        for statement in dependents_statements(sa_inspect(registered.model), obj):
            if (await session.execute(statement)).first() is not None:
                raise ApiError(409, "conflict", "Related records still reference this record.")
        # After the related-records check, so a refused delete never locks admin rows.
        intent = WriteIntent(model=registered.model, obj=obj, action="delete", changes={})
        check = await _guard(request, session, user, intent)
        await session.delete(obj)
        await session.flush()
        if check is not None:
            await check()
    return Response(status_code=204)
