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
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from faststudio.api._db_errors import is_lock_conflict
from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._many import affected_fields, bind_to
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
from faststudio.query._many import (
    INSERT_CHUNK_SIZE,
    chunks,
    delete_links_statement,
    delete_links_to_statement,
    existing_keys_statement,
    insert_links_statement,
    locked_keys_statement,
    touch_record_statement,
)
from faststudio.query._write import dependents_statements, exists_statement
from faststudio.registry import RegisteredModel, Registry
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


def _split_many(
    registered: RegisteredModel, values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Separate column values from many-to-many key lists (ADR-0010)."""
    many = {name: values[name] for name in registered.many_to_many if name in values}
    columns = {name: value for name, value in values.items() if name not in many}
    return columns, many


async def _check_many(
    session: AsyncSession, registered: RegisteredModel, many: dict[str, list[Any]]
) -> None:
    """Every sent key must exist in the target table (422 `foreign_key` otherwise).

    With SQLite's `PRAGMA foreign_keys` off this is the only guard against links
    to missing rows; inserts racing a concurrent delete still fail with 409 where
    the database enforces foreign keys.
    """
    issues: list[ValidationIssue] = []
    for name, keys in many.items():
        link = registered.many_to_many[name].link
        found: set[object] = set()
        for chunk in chunks(keys):
            rows = await session.scalars(
                existing_keys_statement(link, chunk), bind_arguments=bind_to(registered.model)
            )
            found.update(rows.all())
        if any(key not in found for key in keys):
            issues.append(
                ValidationIssue(
                    loc=[name], msg="Referenced record does not exist.", type="foreign_key"
                )
            )
    if issues:
        raise _invalid(issues)


async def _lock_record(session: AsyncSession, registered: RegisteredModel, pk: object) -> None:
    """Serialize concurrent link writes to the same record without changing its row.

    PostgreSQL and MySQL/MariaDB: `SELECT ... FOR UPDATE` on the record's row,
    so host `ON UPDATE` triggers never fire for a links-only write. A second
    writer waits; it then reads the first writer's links under READ COMMITTED
    (PostgreSQL's default), InnoDB REPEATABLE READ (locking read) and
    SERIALIZABLE (aborted with 409). Under PostgreSQL REPEATABLE READ its
    snapshot stays stale, so concurrent link edits of one record may merge
    (documented limitation).

    SQLite has no `FOR UPDATE`: a no-change `UPDATE` takes the database write
    lock (SQLite `ON UPDATE` triggers on the record's table do fire). Other
    dialects are assumed to honour `FOR UPDATE` (FastStudio supports SQLite,
    PostgreSQL and MySQL/MariaDB).
    """
    link = next(iter(registered.many_to_many.values())).link
    bind = bind_to(registered.model)
    if session.get_bind(mapper=bind["mapper"]).dialect.name == "sqlite":
        await session.execute(touch_record_statement(link, pk), bind_arguments=bind)
    else:
        await session.execute(
            select(link.local_pk).where(link.local_pk == pk).with_for_update(),
            bind_arguments=bind,
        )


async def _replace_many(
    session: AsyncSession,
    registered: RegisteredModel,
    pk: object,
    many: dict[str, list[Any]],
    *,
    created: bool,
) -> None:
    """Make each field's links exactly the sent keys: delete the removed, insert the added.

    On update the record is locked first, so the current links are read after
    any concurrent link write committed: two replaces of the same field never
    merge, and identical concurrent adds never store a duplicate pair. A field
    with more than `max_items` links (also after a concurrent write) is refused
    with 422 `truncated`, because a partial list must never be written back.
    """
    if not many:
        return
    bind = bind_to(registered.model)
    if not created:
        await _lock_record(session, registered, pk)
    truncated: list[ValidationIssue] = []
    for name, keys in many.items():
        field = registered.many_to_many[name]
        current: set[object] = set()
        if not created:
            rows = (
                await session.scalars(
                    locked_keys_statement(field.link, pk, field.max_items + 1),
                    bind_arguments=bind,
                )
            ).all()
            # Conservative: duplicate rows (written by other code) count toward the limit.
            if len(rows) > field.max_items:
                truncated.append(
                    ValidationIssue(
                        loc=[name],
                        msg=f"More than {field.max_items} links exist; this field is "
                        "read-only here.",
                        type="truncated",
                    )
                )
                continue
            current = set(rows)
        wanted = set(keys)
        removed = sorted(current - wanted, key=repr)
        added = [key for key in keys if key not in current]
        for chunk in chunks(removed):
            await session.execute(
                delete_links_statement(field.link, pk, chunk), bind_arguments=bind
            )
        for chunk in chunks(added, INSERT_CHUNK_SIZE):  # two bound parameters per key
            await session.execute(
                insert_links_statement(field.link, pk, chunk), bind_arguments=bind
            )
    if truncated:
        raise _invalid(truncated)


async def _delete_links(
    session: AsyncSession, registry: Registry, registered: RegisteredModel, pk: object
) -> None:
    """Remove the links of opted-in many-to-many fields that involve the row `pk`.

    The same fields `GET .../links` counts (ADR-0010 §6, `affected_fields`).
    """
    for item in affected_fields(registry, registered):
        bind = bind_to(item.owner.model)
        if item.own:
            await session.execute(delete_links_statement(item.many.link, pk), bind_arguments=bind)
        if item.pointing:
            await session.execute(
                delete_links_to_statement(item.many.link, pk), bind_arguments=bind
            )


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
    values, many = _split_many(registered, await _validated(request, registered.create_schema))
    await _check_relations(session, registered, values)
    await _check_many(session, registered, many)
    obj = registered.model(**values)
    async with _writing(session, registered, "create"):
        session.add(obj)
        await session.flush()
        pk_value = getattr(obj, registered.pk_field)
        await _replace_many(session, registered, pk_value, many, created=True)
    await session.refresh(obj)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.patch("/models/{identity}/items/{pk}", response_model=Row)
async def update_item(
    request: Request, registered: ModelDep, pk: str, session: DbSession, user: CurrentUser
) -> Row:
    """Change the writable fields sent in the body; primary keys never change."""
    _require(registered.can_edit)
    obj = await load_or_404(session, registered, pk)
    sent = await _validated(request, registered.update_schema)
    values, many = _split_many(registered, sent)
    await _check_relations(session, registered, values)
    pk_value = getattr(obj, registered.pk_field)
    await _check_many(session, registered, many)
    if sent:
        async with _writing(session, registered, "update"):
            # The guard sees many-to-many fields too, as lists of keys (ADR-0010 §5).
            intent = WriteIntent(model=registered.model, obj=obj, action="update", changes=sent)
            check = await _guard(request, session, user, intent)
            for name, value in values.items():
                setattr(obj, name, value)
            await _replace_many(session, registered, pk_value, many, created=False)
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

    Links of opted-in many-to-many fields involving the record (its own fields
    and fields of other models pointing at it) are removed in the same
    transaction (ADR-0010 §6). Otherwise the delete is refused with 409 while an
    ORM relationship it would touch still has related rows (one-to-many,
    many-to-many that is not opted in, or many-to-one with a delete cascade), so
    ORM cascades do not change rows of other models. Rows added concurrently
    between this check and the flush are not covered; database foreign-key
    rules still apply and also give 409.
    """
    _require(registered.can_delete)
    obj = await load_or_404(session, registered, pk)
    async with _writing(session, registered, "delete"):
        registry = get_context(request).registry
        await _delete_links(session, registry, registered, getattr(obj, registered.pk_field))
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
