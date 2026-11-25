"""Read API: metadata, lists, single records, relation choices and delete previews."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from faststudio.api._authz import Perms, allowed, require, resolve_permissions, viewable
from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._many import link_counts
from faststudio.api._paths import API_PREFIX
from faststudio.api._records import detail_row, load_or_404
from faststudio.api._serialize import encode_pk, format_label, relation_labels, to_row
from faststudio.api.auth import CurrentUser, current_user, get_context
from faststudio.api.errors import ApiError
from faststudio.query._list import choices_statements, list_statements
from faststudio.query._params import parse_choices_params, parse_list_params
from faststudio.schemas._meta import build_models_meta
from faststudio.schemas.contract import (
    SCHEMA_VERSION,
    ChoiceMeta,
    ChoicesResponse,
    LinkCountsResponse,
    ListResponse,
    MetaResponse,
    PermissionsMeta,
    Row,
    UserMeta,
)

# Every route resolves the admin's permissions first (ADR-0011 §5; route test).
router = APIRouter(
    prefix=API_PREFIX, dependencies=[Depends(current_user), Depends(resolve_permissions)]
)


@router.get("/meta", response_model=MetaResponse)
async def meta(request: Request, user: CurrentUser, perms: Perms) -> MetaResponse:
    """Describe the models the admin may view, with their permissions on each."""
    # Imported here: `faststudio/__init__.py` (the version's single source) imports the app.
    from faststudio import __version__  # noqa: PLC0415

    del perms  # resolved: the hooks read it
    context = get_context(request)
    guard = context.capabilities.account_guard
    permissions = {
        registered.identity: PermissionsMeta(
            view=True,
            create=await allowed(request, registered, "create"),
            edit=await allowed(request, registered, "edit"),
            delete=await allowed(request, registered, "delete"),
        )
        for registered in context.registry
        if registered.identity in await viewable(request)
    }
    return MetaResponse(
        schema_version=SCHEMA_VERSION,
        version=__version__,
        title=context.settings.title,
        show_powered_by=context.settings.show_powered_by,
        user=UserMeta(id=user.id, username=user.username),
        models=build_models_meta(context.registry, guard=guard, permissions=permissions),
    )


@router.get("/models/{identity}/items", response_model=ListResponse)
async def list_items(request: Request, registered: ModelDep, session: DbSession) -> ListResponse:
    """Return a page of records with search, filters and sorting from the allowlists."""
    await require(request, registered, "view")
    context = get_context(request)
    settings = context.settings
    params = parse_list_params(
        request.query_params.multi_items(),
        registered,
        settings.max_page_size,
        max_list_offset=settings.max_list_offset,
    )
    page_query, count_query = list_statements(registered, params)
    rows = (await session.execute(page_query)).scalars().all()
    total = (await session.execute(count_query)).scalar_one()
    fields = registered.list_display
    labels = await relation_labels(
        session, context.registry, registered, rows, fields, visible=await viewable(request)
    )
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
    """Return one record with all visible fields.

    A record the view hook refuses is a 404, like a missing one (no oracle).
    """
    await require(request, registered, "view")
    obj = await load_or_404(session, registered, pk)
    if not await allowed(request, registered, "view", obj):
        raise ApiError(404, "not_found")
    registry = get_context(request).registry
    return await detail_row(session, registry, registered, obj, await viewable(request))


@router.get("/models/{identity}/items/{pk}/links", response_model=LinkCountsResponse)
async def item_links(
    request: Request, registered: ModelDep, pk: str, session: DbSession
) -> LinkCountsResponse:
    """Count the many-to-many links deleting this record would remove (ADR-0010 §6).

    For the delete confirmation, so it needs the delete permission (on the
    record too). Lists every affected opted-in field, also those with no links,
    except fields of models the admin may not view.
    """
    await require(request, registered, "delete")
    obj = await load_or_404(session, registered, pk)
    if registered.identity in await viewable(request) and not await allowed(
        request, registered, "view", obj
    ):
        raise ApiError(404, "not_found")  # hidden from retrieve, so hidden here too
    await require(request, registered, "delete", obj)
    registry = get_context(request).registry
    pk_value = getattr(obj, registered.pk_field)
    counts = await link_counts(session, registry, registered, pk_value, await viewable(request))
    return LinkCountsResponse(items=counts)


@router.get("/models/{identity}/fields/{field}/choices", response_model=ChoicesResponse)
async def choices(
    request: Request, registered: ModelDep, field: str, session: DbSession
) -> ChoicesResponse:
    """Return options for a relation field whose target model is registered.

    Choices are for forms: they need create or edit on this model, and view on
    the target (else 403; A1).
    """
    if not (
        await allowed(request, registered, "create") or await allowed(request, registered, "edit")
    ):
        raise ApiError(403, "forbidden")
    registry = get_context(request).registry
    spec = registered.field_specs.get(field)
    many = registered.many_to_many.get(field)
    if spec is not None and spec.relation is not None:
        target = registry.target_of(spec.relation.target)
    elif many is not None:  # a many-to-many field picks keys of its target (ADR-0010)
        target = registry.target_of(many.link.target_pk)
    else:
        target = None
    if target is None:
        raise ApiError(404, "not_found")
    if target.identity not in await viewable(request):
        raise ApiError(403, "forbidden")
    page, q = parse_choices_params(
        request.query_params.multi_items(),
        max_list_offset=get_context(request).settings.max_list_offset,
    )
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
