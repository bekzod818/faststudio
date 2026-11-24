"""Read API: metadata, lists, single records and relation choices (M7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._paths import API_PREFIX
from faststudio.api._records import detail_row, load_or_404
from faststudio.api._serialize import encode_pk, format_label, relation_labels, to_row
from faststudio.api.auth import CurrentUser, current_user, get_context
from faststudio.api.errors import ApiError
from faststudio.auth._guard import AccountGuard
from faststudio.query._list import choices_statements, list_statements
from faststudio.query._params import parse_choices_params, parse_list_params
from faststudio.schemas._meta import build_models_meta
from faststudio.schemas.contract import (
    SCHEMA_VERSION,
    ChoiceMeta,
    ChoicesResponse,
    ListResponse,
    MetaResponse,
    Row,
    UserMeta,
)

router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])


@router.get("/meta", response_model=MetaResponse)
async def meta(request: Request, user: CurrentUser) -> MetaResponse:
    """Describe every registered model for the SPA."""
    # Imported here: `faststudio/__init__.py` (the version's single source) imports the app.
    from faststudio import __version__  # noqa: PLC0415

    context = get_context(request)
    backend = context.auth_backend
    guard = backend if isinstance(backend, AccountGuard) else None
    return MetaResponse(
        schema_version=SCHEMA_VERSION,
        version=__version__,
        title=context.settings.title,
        show_powered_by=context.settings.show_powered_by,
        user=UserMeta(id=user.id, username=user.username),
        models=build_models_meta(context.registry, guard=guard),
    )


@router.get("/models/{identity}/items", response_model=ListResponse)
async def list_items(request: Request, registered: ModelDep, session: DbSession) -> ListResponse:
    """Return a page of records with search, filters and sorting from the allowlists."""
    context = get_context(request)
    params = parse_list_params(
        request.query_params.multi_items(), registered, context.settings.max_page_size
    )
    page_query, count_query = list_statements(registered, params)
    rows = (await session.execute(page_query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()
    fields = registered.list_display
    labels = await relation_labels(session, context.registry, registered, rows, fields)
    return ListResponse(
        items=[
            to_row(registered, row, fields, label) for row, label in zip(rows, labels, strict=True)
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/models/{identity}/items/{pk}", response_model=Row)
async def retrieve_item(request: Request, registered: ModelDep, pk: str, session: DbSession) -> Row:
    """Return one record with all visible fields."""
    obj = await load_or_404(session, registered, pk)
    return await detail_row(session, get_context(request).registry, registered, obj)


@router.get("/models/{identity}/fields/{field}/choices", response_model=ChoicesResponse)
async def choices(
    request: Request, registered: ModelDep, field: str, session: DbSession
) -> ChoicesResponse:
    """Return options for a foreign-key field whose target model is registered."""
    registry = get_context(request).registry
    spec = registered.field_specs.get(field)
    target = registry.target_of(spec.relation.target) if spec and spec.relation else None
    if target is None:
        raise ApiError(404, "not_found")
    page, q = parse_choices_params(request.query_params.multi_items())
    page_query, count_query = choices_statements(target, q, page)
    total = (await session.execute(count_query)).scalar_one()
    result = await session.execute(page_query)
    return ChoicesResponse(
        items=[
            ChoiceMeta(value=encode_pk(pk), label=format_label(pk, label))
            for pk, label in result.all()
        ],
        total=total,
    )
