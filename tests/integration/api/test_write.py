"""POST / PATCH / DELETE with mass-assignment protection (M8, threat model T5)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tests.factories.models import Child, Country, Note, Owner, Role, Team, User

BASE = "/admin/api/v1/models"
CSRF = "x-faststudio-csrf"


def _headers(api: httpx.AsyncClient) -> dict[str, str]:
    token = api.cookies.get("faststudio_csrftoken")
    assert token
    return {CSRF: token}


async def _post(api: httpx.AsyncClient, identity: str, body: object) -> httpx.Response:
    return await api.post(f"{BASE}/{identity}/items", json=body, headers=_headers(api))


async def _patch(api: httpx.AsyncClient, identity: str, pk: str, body: object) -> httpx.Response:
    return await api.patch(f"{BASE}/{identity}/items/{pk}", json=body, headers=_headers(api))


async def _note(db: AsyncEngine, pk: int) -> Note | None:
    async with async_sessionmaker(db)() as session:
        return await session.get(Note, pk)


def _issues(response: httpx.Response) -> list[tuple[list[Any], str]]:
    body = response.json()
    assert body["error"]["code"] == "validation_error", body
    return [(issue["loc"], issue["type"]) for issue in body["error"]["details"]]


# --------------------------------------------------------------------------- create


async def test_create_returns_full_row(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await _post(
        api, "notes", {"title": "hello", "priority": 3, "status": "EDITOR", "team_id": 2}
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["pk"] == "2"
    assert row["data"]["title"] == "hello"
    assert row["data"]["status"] == "EDITOR"
    assert row["labels"] == {"team_id": "Growth"}
    assert "secret" not in row["data"]
    assert "s3cret-default" not in response.text
    stored = await _note(db, 2)
    assert stored is not None
    assert (stored.priority, stored.status, stored.secret) == (3, Role.EDITOR, "s3cret-default")


async def test_create_uses_defaults_for_omitted_fields(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"title": "minimal"})
    assert response.status_code == 201
    assert response.json()["data"]["priority"] == 0


async def test_create_requires_required_fields(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"body": "no title"})
    assert response.status_code == 422
    assert (["title"], "missing") in _issues(response)


@pytest.mark.parametrize(
    "field",
    ["secret", "created_at", "id", "unknown", "password_hash", "__class__"],
)
async def test_mass_assignment_is_rejected(
    api: httpx.AsyncClient, db: AsyncEngine, field: str
) -> None:
    response = await _post(api, "notes", {"title": "x", field: "1"})
    assert response.status_code == 422
    assert ([field], "extra_forbidden") in _issues(response)
    assert await _note(db, 2) is None  # nothing written


async def test_create_only_natural_key(api: httpx.AsyncClient) -> None:
    response = await _post(api, "countries", {"code": "KZ", "name": "Kazakhstan"})
    assert response.status_code == 201
    assert response.json()["pk"] == "KZ"


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"title": "x" * 21}, ["title"]),
        ({"title": "nul\x00byte"}, ["title"]),
        ({"title": "x", "body": "y" * 65_536}, ["body"]),
        ({"title": None}, ["title"]),
        ({"title": 5}, ["title"]),
        ({"title": "x", "priority": 40_000}, ["priority"]),
        ({"title": "x", "priority": True}, ["priority"]),
        ({"title": "x", "priority": 1.5}, ["priority"]),
        ({"title": "x", "priority": "1e3"}, ["priority"]),
        ({"title": "x", "priority": None}, ["priority"]),
        ({"title": "x", "status": "editor"}, ["status"]),
        ({"title": "x", "status": "SUPERUSER"}, ["status"]),
        ({"title": "x", "team_id": 999}, ["team_id"]),
        ({"title": "x", "team_id": "abc"}, ["team_id"]),
        ({"title": "x", "due": "2026-01-02T03:04:05+05:00"}, ["due"]),
        ({"title": "x", "due": "yesterday"}, ["due"]),
    ],
)
async def test_invalid_values_are_rejected(
    api: httpx.AsyncClient, body: dict[str, Any], loc: list[Any]
) -> None:
    response = await _post(api, "notes", body)
    assert response.status_code == 422, response.text
    assert loc in [issue_loc for issue_loc, _ in _issues(response)]
    assert "\x00" not in response.text


async def test_integer_accepted_as_digit_string(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"title": "x", "priority": "7"})
    assert response.status_code == 201
    assert response.json()["data"]["priority"] == 7


async def test_big_integer_round_trips_as_string(api: httpx.AsyncClient) -> None:
    response = await _patch(api, "gauges", "1", {"big": str(2**62)})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["big"] == str(2**62)


@pytest.mark.parametrize("amount", ["1.234", "123456789.00", "NaN", "abc"])
async def test_decimal_precision_is_enforced(api: httpx.AsyncClient, amount: str) -> None:
    response = await _patch(api, "gauges", "1", {"amount": amount})
    assert response.status_code == 422


async def test_aware_datetime_column_assumes_utc(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"title": "x", "stamped": "2026-01-02T03:04:05"})
    assert response.status_code == 201
    assert response.json()["data"]["stamped"].startswith("2026-01-02T03:04:05")


async def test_foreign_key_null_is_allowed(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"title": "x", "team_id": None})
    assert response.status_code == 201


# --------------------------------------------------------------------------- update


async def test_partial_update(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await _patch(api, "notes", "1", {"body": "edited"})
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "first"
    stored = await _note(db, 1)
    assert stored is not None
    assert (stored.body, stored.title, stored.secret) == ("edited", "first", "NOTE-SECRET")


async def test_update_can_clear_nullable_field(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    assert (await _patch(api, "notes", "1", {"team_id": None})).status_code == 200
    stored = await _note(db, 1)
    assert stored is not None
    assert stored.team_id is None


@pytest.mark.parametrize("field", ["id", "secret", "created_at", "nope"])
async def test_update_mass_assignment_is_rejected(
    api: httpx.AsyncClient, db: AsyncEngine, field: str
) -> None:
    response = await _patch(api, "notes", "1", {field: "2"})
    assert response.status_code == 422
    assert ([field], "extra_forbidden") in _issues(response)
    stored = await _note(db, 1)
    assert stored is not None
    assert (stored.id, stored.secret) == (1, "NOTE-SECRET")


async def test_update_cannot_change_natural_key(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await _patch(api, "countries", "UZ", {"code": "XX"})
    assert response.status_code == 422
    assert (["code"], "extra_forbidden") in _issues(response)
    renamed = await _patch(api, "countries", "UZ", {"name": "O'zbekiston"})
    assert renamed.status_code == 200
    assert renamed.json()["pk"] == "UZ"
    async with async_sessionmaker(db)() as session:
        assert await session.get(Country, "XX") is None


@pytest.mark.parametrize("pk", ["999", "abc"])
async def test_update_missing_row_is_404(api: httpx.AsyncClient, pk: str) -> None:
    assert (await _patch(api, "notes", pk, {"body": "x"})).status_code == 404


async def test_empty_update_is_a_no_op(api: httpx.AsyncClient) -> None:
    response = await _patch(api, "notes", "1", {})
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "first"


# --------------------------------------------------------------------------- delete


async def test_delete(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await api.delete(f"{BASE}/notes/items/1", headers=_headers(api))
    assert response.status_code == 204
    assert await _note(db, 1) is None
    again = await api.delete(f"{BASE}/notes/items/1", headers=_headers(api))
    assert again.status_code == 404


async def test_delete_referenced_row_is_conflict(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await api.delete(f"{BASE}/teams/items/1", headers=_headers(api))
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Conflict.", "details": None}
    }
    async with async_sessionmaker(db)() as session:
        assert await session.get(Team, 1) is not None


async def test_unique_violation_is_conflict_without_sql(api: httpx.AsyncClient) -> None:
    response = await _post(api, "countries", {"code": "UZ", "name": "Again"})
    assert response.status_code == 409
    assert "UNIQUE" not in response.text
    assert "countries" not in response.text


# --------------------------------------------------------------------------- permissions


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "managers/items"),
        ("PATCH", "managers/items/3"),
        ("DELETE", "countries/items/UZ"),
    ],
)
async def test_disabled_actions_are_forbidden(
    api: httpx.AsyncClient, db: AsyncEngine, method: str, path: str
) -> None:
    response = await api.request(
        method, f"{BASE}/{path}", json={"name": "x"}, headers=_headers(api)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    async with async_sessionmaker(db)() as session:
        country = await session.get(Country, "UZ")
        assert country is not None
        assert country.name == "Uzbekistan"


async def test_writes_require_csrf(api: httpx.AsyncClient) -> None:
    response = await api.post(f"{BASE}/notes/items", json={"title": "x"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_unknown_model_is_404(api: httpx.AsyncClient) -> None:
    assert (await _post(api, "nope", {})).status_code == 404


# --------------------------------------------------------------------------- body handling


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{not json", "application/json"),
        (b"[1, 2]", "application/json"),
        (b'"title"', "application/json"),
        (b"", "application/json"),
        (b"title=x", "application/x-www-form-urlencoded"),
        (b'{"title": "x"}', "text/plain"),
    ],
)
async def test_body_must_be_a_json_object(
    api: httpx.AsyncClient, content: bytes, content_type: str
) -> None:
    response = await api.post(
        f"{BASE}/notes/items",
        content=content,
        headers={**_headers(api), "content-type": content_type},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_oversized_body_is_rejected(api: httpx.AsyncClient) -> None:
    payload = b'{"title": "' + b"x" * (1024 * 1024 + 10) + b'"}'
    response = await api.post(
        f"{BASE}/notes/items",
        content=payload,
        headers={**_headers(api), "content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_is_rejected(api: httpx.AsyncClient) -> None:
    async def chunks() -> Any:
        yield b'{"title": "'
        for _ in range(130):
            yield b"x" * 8192
        yield b'"}'

    response = await api.post(
        f"{BASE}/notes/items",
        content=chunks(),
        headers={**_headers(api), "content-type": "application/json"},
    )
    assert response.status_code == 413


async def test_validation_errors_never_echo_values(api: httpx.AsyncClient) -> None:
    response = await _post(api, "notes", {"title": "SECRET-VALUE" * 3, "priority": "SECRET-INT"})
    assert response.status_code == 422
    assert "SECRET-VALUE" not in response.text
    assert "SECRET-INT" not in response.text


async def test_writes_do_not_leak_excluded_values_in_list(api: httpx.AsyncClient) -> None:
    await _post(api, "notes", {"title": "x"})
    listing = await api.get(f"{BASE}/notes/items")
    assert "s3cret" not in listing.text
    assert "NOTE-SECRET" not in listing.text


async def test_row_reflects_database_after_write(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await _post(api, "teams", {"name": "Design"})
    assert response.status_code == 201
    async with async_sessionmaker(db)() as session:
        names = (await session.execute(select(Team.name).order_by(Team.id))).scalars().all()
    assert names[-1] == "Design"
    assert response.json() == {"pk": "4", "data": {"id": 4, "name": "Design"}, "labels": {}}


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "managers/items"), ("PATCH", "managers/items/3")]
)
@pytest.mark.parametrize(
    "body",
    [
        (b"x" * (2 * 1024 * 1024), "application/json"),
        (b"title=x", "text/plain"),
    ],
)
async def test_permission_is_checked_before_the_body(
    api: httpx.AsyncClient, method: str, path: str, body: tuple[bytes, str]
) -> None:
    content, content_type = body
    response = await api.request(
        method,
        f"{BASE}/{path}",
        content=content,
        headers={**_headers(api), "content-type": content_type},
    )
    assert response.status_code == 403


async def test_update_foreign_key_must_exist(api: httpx.AsyncClient) -> None:
    response = await _patch(api, "notes", "1", {"team_id": 999})
    assert response.status_code == 422
    assert (["team_id"], "foreign_key") in _issues(response)


async def test_update_unique_violation_is_conflict(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await _patch(api, "users", "2", {"email": "user01@example.com"})
    assert response.status_code == 409
    async with async_sessionmaker(db)() as session:
        user = await session.get(User, 2)
        assert user is not None
        assert user.email == "user02@example.com"


async def test_delete_refused_while_orm_relationship_has_rows(
    api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    response = await api.delete(f"{BASE}/parents/items/1", headers=_headers(api))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    async with async_sessionmaker(db)() as session:
        child = await session.get(Child, 1)
        assert child is not None
        assert child.parent_id == 1  # never nulled or deleted behind the admin's back


async def test_delete_without_related_rows(api: httpx.AsyncClient) -> None:
    response = await api.delete(f"{BASE}/parents/items/2", headers=_headers(api))
    assert response.status_code == 204


async def test_json_values_must_be_storable(api: httpx.AsyncClient) -> None:
    for raw in (b'{"doc": NaN}', b'{"doc": {"k\\u0000": 1}}', b'{"doc": [1e400]}'):
        response = await api.patch(
            f"{BASE}/gauges/items/1",
            content=raw,
            headers={**_headers(api), "content-type": "application/json"},
        )
        assert response.status_code == 422, raw


async def test_many_to_one_relationship_does_not_block_delete(
    api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    response = await api.delete(f"{BASE}/children/items/1", headers=_headers(api))
    assert response.status_code == 204
    async with async_sessionmaker(db)() as session:
        assert await session.get(Child, 1) is None
    assert (await api.delete(f"{BASE}/parents/items/1", headers=_headers(api))).status_code == 204


async def test_many_to_one_delete_cascade_is_refused(
    api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    """`Pet.owner` cascades deletes: deleting the pet would delete the owner."""
    response = await api.delete(f"{BASE}/pets/items/1", headers=_headers(api))
    assert response.status_code == 409
    async with async_sessionmaker(db)() as session:
        assert await session.get(Owner, 1) is not None
    unowned = await api.delete(f"{BASE}/pets/items/2", headers=_headers(api))
    assert unowned.status_code == 204


async def test_many_to_many_links_block_delete(api: httpx.AsyncClient) -> None:
    tagged = await api.delete(f"{BASE}/posts/items/1", headers=_headers(api))
    assert tagged.status_code == 409
    plain = await api.delete(f"{BASE}/posts/items/2", headers=_headers(api))
    assert plain.status_code == 204
