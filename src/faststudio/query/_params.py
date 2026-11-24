"""Strict parsing of list and choices query parameters (threat model T4)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Enum

from faststudio.api.errors import ApiError
from faststudio.introspection._columns import base_type
from faststudio.registry import RegisteredModel

MAX_QUERY_LENGTH = 200
MAX_ORDERING_FIELDS = 5
CHOICES_PAGE_SIZE = 20
_FILTER_KEY = re.compile(r"filter\[(.+)\]")
_DIGITS = re.compile(r"[0-9]{1,9}")


@dataclass(frozen=True, slots=True)
class ListParams:
    """Validated list parameters; every field name is from the model's allowlists."""

    page: int
    page_size: int
    q: str | None
    ordering: tuple[tuple[str, bool], ...]
    filters: Mapping[str, object]


def _invalid(message: str) -> ApiError:
    # Messages name the parameter, never echo the submitted value.
    return ApiError(400, "invalid_query", message)


def _single(
    items: Sequence[tuple[str, str]], allowed: set[str], *, allow_filters: bool
) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in items:
        if key not in allowed and not (allow_filters and _FILTER_KEY.fullmatch(key)):
            msg = "Unknown query parameter."
            raise _invalid(msg)
        if key in values:
            msg = "Query parameters must not be repeated."
            raise _invalid(msg)
        values[key] = value
    return values


def last_reachable_page(max_list_offset: int, page_size: int) -> int:
    """Return the last page whose OFFSET, ``(page - 1) * page_size``, is below the cap.

    The SPA computes the same value (`lastReachablePage` in features/list/query.ts).
    """
    return -(-max_list_offset // page_size)


def _page(raw: str | None, *, page_size: int, max_list_offset: int) -> int:
    """Parse `page` and refuse pages past the offset cap (threat model: read cost)."""
    if raw is None:
        return 1
    if not _DIGITS.fullmatch(raw) or int(raw) < 1:
        msg = "`page` must be a positive integer."
        raise _invalid(msg)
    page = int(raw)
    if page > last_reachable_page(max_list_offset, page_size):
        msg = "`page` is past the last reachable page; narrow the results with search or filters."
        raise _invalid(msg)
    return page


def _positive(raw: str | None, *, name: str, default: int, maximum: int) -> int:
    if raw is None:
        return default
    if not _DIGITS.fullmatch(raw) or not 1 <= int(raw) <= maximum:
        msg = f"`{name}` must be an integer between 1 and {maximum}."
        raise _invalid(msg)
    return int(raw)


def parse_search(raw: str | None) -> str | None:
    """Return the trimmed search text, or None when empty."""
    if raw is None:
        return None
    if len(raw) > MAX_QUERY_LENGTH:
        msg = f"`q` must be at most {MAX_QUERY_LENGTH} characters."
        raise _invalid(msg)
    if any(unicodedata.category(ch) == "Cc" for ch in raw):
        msg = "`q` must not contain control characters."
        raise _invalid(msg)
    text = raw.strip()
    return text or None


def _ordering(raw: str | None, registered: RegisteredModel) -> tuple[tuple[str, bool], ...]:
    if raw is None:
        return registered.ordering
    parts = raw.split(",")
    if len(parts) > MAX_ORDERING_FIELDS:
        msg = f"`ordering` accepts at most {MAX_ORDERING_FIELDS} fields."
        raise _invalid(msg)
    result: list[tuple[str, bool]] = []
    for part in (p.strip() for p in parts):
        descending = part.startswith("-")
        name = part[1:] if descending else part
        if name not in registered.sortable_fields or name in {f for f, _ in result}:
            msg = "`ordering` contains a field that cannot be sorted."
            raise _invalid(msg)
        result.append((name, descending))
    return tuple(result)


def _filter_value(registered: RegisteredModel, name: str, raw: str) -> object:
    spec = registered.field_specs[name]
    if raw == "null" and spec.nullable:
        return None
    if spec.type == "boolean":
        if raw in {"true", "false"}:
            return raw == "true"
    elif spec.choices is not None and raw in {c.value for c in spec.choices}:
        type_ = base_type(spec.column.type)
        if isinstance(type_, Enum) and type_.enum_class is not None:
            return type_.enum_class[raw]
        return raw
    msg = "A filter value is not one of the allowed choices."
    raise _invalid(msg)


def parse_list_params(
    items: Sequence[tuple[str, str]],
    registered: RegisteredModel,
    max_page_size: int,
    *,
    max_list_offset: int,
) -> ListParams:
    """Validate list query parameters against the model's allowlists.

    Raises:
        ApiError: `400 invalid_query` for anything not explicitly allowed.

    """
    values = _single(items, {"page", "page_size", "q", "ordering"}, allow_filters=True)
    filters: dict[str, object] = {}
    for key, raw in values.items():
        match = _FILTER_KEY.fullmatch(key)
        if match is None:
            continue
        name = match.group(1)
        if name not in registered.list_filter:
            msg = "Unknown filter."
            raise _invalid(msg)
        filters[name] = _filter_value(registered, name, raw)
    page_size = _positive(
        values.get("page_size"),
        name="page_size",
        default=registered.page_size,
        maximum=max_page_size,
    )
    return ListParams(
        page=_page(values.get("page"), page_size=page_size, max_list_offset=max_list_offset),
        page_size=page_size,
        q=parse_search(values.get("q")),
        ordering=_ordering(values.get("ordering"), registered),
        filters=filters,
    )


def parse_choices_params(
    items: Sequence[tuple[str, str]], *, max_list_offset: int
) -> tuple[int, str | None]:
    """Validate `page` and `q` for the choices endpoint."""
    values = _single(items, {"page", "q"}, allow_filters=False)
    page = _page(values.get("page"), page_size=CHOICES_PAGE_SIZE, max_list_offset=max_list_offset)
    return page, parse_search(values.get("q"))
