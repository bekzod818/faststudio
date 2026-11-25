"""Authorization on every route (ADR-0011 §4-5, threat model T9, M17).

Users hold permissions through a test backend with the permission capability
(`tests/factories/auth_models.py`). Runs on SQLite, and on PostgreSQL when
FASTSTUDIO_TEST_POSTGRES_URL points at a throwaway `*_test` database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from starlette.requests import Request

from faststudio import Admin, ModelAdmin, hash_password
from faststudio.auth.permissions import has_perm
from tests.factories.auth_models import (
    AuthBase,
    AuthGroup,
    AuthPermission,
    AuthUser,
    Badge,
    Doc,
    Folder,
    PermBackend,
    doc_badges,
    group_permissions,
    user_groups,
    user_permissions,
)

ORIGIN = "https://testserver"
API = "/admin/api/v1"
PASSWORD = "a long test passphrase"
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")

#: Doc levels: >= 9 hidden unless the user holds docs.publish, >= 5 locked for edit/delete.
SECRET, LOCKED = 9, 5


class DocAdmin(ModelAdmin, model=Doc):
    identity = "docs"
    list_display = ("id", "title", "folder_id")
    many_to_many = ("badges",)
    extra_permissions = {"publish": "Publish documents"}  # noqa: RUF012 - a ModelAdmin option

    @classmethod
    async def has_view_permission(cls, request: Request, obj: object | None = None) -> bool:
        if (
            isinstance(obj, Doc)
            and obj.level >= SECRET
            and not await has_perm(request, "docs.publish")
        ):
            return False
        return await super().has_view_permission(request, obj)

    @classmethod
    async def has_edit_permission(cls, request: Request, obj: object | None = None) -> bool:
        if isinstance(obj, Doc) and obj.level >= LOCKED:
            return False
        return await super().has_edit_permission(request, obj)

    @classmethod
    async def has_delete_permission(cls, request: Request, obj: object | None = None) -> bool:
        if isinstance(obj, Doc) and obj.level >= LOCKED:
            return False
        return await super().has_delete_permission(request, obj)


class FolderAdmin(ModelAdmin, model=Folder):
    identity = "folders"
    list_display = ("id", "name")


class BadgeAdmin(ModelAdmin, model=Badge):
    identity = "badges"
    list_display = ("id", "name")


#: username -> codenames (granted directly); "root" is a superuser.
USERS: dict[str, tuple[str, ...]] = {
    "root": (),
    "viewer": ("docs.view", "folders.view", "badges.view"),
    "editor": ("docs.edit", "folders.view", "badges.view"),
    "blind_editor": ("docs.edit",),  # cannot view folders or badges
    "creator": ("docs.create",),  # create without view (API only)
    "full_creator": ("docs.create", "docs.view", "folders.view", "badges.view"),
    "deleter": ("docs.delete",),  # delete without view (API only)
    "curator": ("docs.view", "docs.delete"),
    "nobody": (),
}
GROUPED = "member"  # holds docs.view through a group


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
            ],
        ),
    ]
)
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if request.param == "postgres":
        name = make_url(POSTGRES_URL).database or ""
        if not name.endswith("_test"):
            pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
        engine = create_async_engine(POSTGRES_URL)
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/authz.db")
    async with engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.drop_all)
        await conn.run_sync(AuthBase.metadata.create_all)
    password_hash = hash_password(PASSWORD)
    codenames = sorted({c for granted in USERS.values() for c in granted} | {"docs.publish"})
    async with AsyncSession(engine) as session:
        session.add_all(AuthPermission(id=i, codename=c) for i, c in enumerate(codenames, 1))
        ids = {c: i for i, c in enumerate(codenames, 1)}
        names = [*USERS, GROUPED]
        session.add_all(
            AuthUser(
                id=i,
                username=name,
                password_hash=password_hash,
                is_superuser=name == "root",
            )
            for i, name in enumerate(names, 1)
        )
        session.add(AuthGroup(id=1, name="readers"))
        session.add_all([Folder(id=1, name="Plans"), Folder(id=2, name="Notes")])
        session.add_all([Badge(id=1, name="draft"), Badge(id=2, name="final")])
        session.add_all(
            [
                Doc(id=1, title="open", level=0, folder_id=1),
                Doc(id=2, title="locked", level=LOCKED, folder_id=1),
                Doc(id=3, title="secret", level=SECRET, folder_id=2),
                Doc(id=4, title="spare", level=0),
            ]
        )
        await session.flush()
        grants = [
            {"user_id": names.index(user) + 1, "permission_id": ids[c]}
            for user, granted in USERS.items()
            for c in granted
        ]
        if grants:
            await session.execute(insert(user_permissions), grants)
        await session.execute(
            insert(group_permissions), [{"group_id": 1, "permission_id": ids["docs.view"]}]
        )
        await session.execute(
            insert(user_groups), [{"user_id": names.index(GROUPED) + 1, "group_id": 1}]
        )
        await session.execute(insert(doc_badges), [{"doc_id": 1, "badge_id": 1}])
        if request.param == "postgres":  # explicit ids do not advance sequences
            for table in (
                "t_docs",
                "t_folders",
                "t_badges",
                "t_users",
                "t_groups",
                "t_permissions",
            ):
                await session.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT max(id) FROM {table}))"
                    )
                )
        await session.commit()
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(AuthBase.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def admin(app: FastAPI, db: AsyncEngine, secret_key: str) -> Admin:
    instance = Admin(app, engine=db, auth_backend=PermBackend(), secret_key=secret_key)
    for admin_class in (DocAdmin, FolderAdmin, BadgeAdmin):
        instance.register(admin_class)
    return instance


class Client:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.http.get(f"{API}{path}", params=params)

    async def post(self, path: str, body: object) -> httpx.Response:
        return await self.http.post(f"{API}{path}", json=body, headers=self._headers())

    async def patch(self, path: str, body: object) -> httpx.Response:
        return await self.http.patch(f"{API}{path}", json=body, headers=self._headers())

    async def delete(self, path: str) -> httpx.Response:
        return await self.http.delete(f"{API}{path}", headers=self._headers())


SignIn = Callable[[str], Awaitable[Client]]


@pytest.fixture
async def sign_in(app: FastAPI, admin: Admin) -> AsyncIterator[SignIn]:
    del admin  # mounted
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str) -> Client:
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
            )
            await http.get(f"{API}/auth/me")
            response = await http.post(
                f"{API}/auth/login",
                json={"username": username, "password": PASSWORD},
                headers={
                    "x-faststudio-csrf": http.cookies["faststudio_csrftoken"],
                    "origin": ORIGIN,
                },
            )
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


def _code(response: httpx.Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


# --------------------------------------------------------------------------- /meta


async def _models(client: Client) -> dict[str, dict[str, Any]]:
    meta = (await client.get("/meta")).json()
    return {m["identity"]: m for m in meta["models"]}


async def test_meta_lists_only_viewable_models_with_their_permissions(sign_in: SignIn) -> None:
    root = await _models(await sign_in("root"))
    assert list(root) == ["docs", "folders", "badges"]
    assert root["docs"]["permissions"] == {
        "view": True,
        "create": True,
        "edit": True,
        "delete": True,
    }
    viewer = await _models(await sign_in("viewer"))
    assert list(viewer) == ["docs", "folders", "badges"]
    assert viewer["docs"]["permissions"] == {
        "view": True,
        "create": False,
        "edit": False,
        "delete": False,
    }
    editor = await _models(await sign_in("editor"))
    assert editor["docs"]["permissions"]["edit"] is True  # edit implies view
    assert list(await _models(await sign_in("member"))) == ["docs"]  # through a group
    assert await _models(await sign_in("nobody")) == {}
    assert await _models(await sign_in("creator")) == {}  # create without view: API only


async def test_meta_hides_relation_targets_the_user_cannot_view(sign_in: SignIn) -> None:
    fields = {
        f["name"]: f for f in (await _models(await sign_in("blind_editor")))["docs"]["fields"]
    }
    for name in ("folder_id", "badges"):
        assert fields[name]["relation"]["target_identity"] is None, name
        assert fields[name]["relation"]["target_field"] is None, name
        assert fields[name]["readonly"] is True, name
    editor = {f["name"]: f for f in (await _models(await sign_in("editor")))["docs"]["fields"]}
    assert editor["folder_id"]["relation"]["target_identity"] == "folders"
    assert editor["folder_id"]["readonly"] is False


# --------------------------------------------------------------------------- the 403 matrix

#: (method, path, body). Each needs a permission the "nobody" user lacks.
ROUTES = [
    ("GET", "/models/docs/items", None),
    ("GET", "/models/docs/items/1", None),
    ("GET", "/models/docs/items/1/links", None),
    ("GET", "/models/docs/fields/folder_id/choices", None),
    ("POST", "/models/docs/items", {"title": "x"}),
    ("PATCH", "/models/docs/items/1", {"title": "x"}),
    ("DELETE", "/models/docs/items/1", None),
]

#: Who may do what on docs, by route: True allowed, else the expected status.
MATRIX: dict[str, dict[str, bool | int]] = {
    "nobody": dict.fromkeys(["list", "get", "links", "choices", "post", "patch", "delete"], 403),
    "viewer": {
        "list": True,
        "get": True,
        "links": 403,
        "choices": 403,
        "post": 403,
        "patch": 403,
        "delete": 403,
    },
    "editor": {
        "list": True,
        "get": True,
        "links": 403,
        "choices": True,
        "post": 403,
        "patch": True,
        "delete": 403,
    },
    "creator": {
        "list": 403,
        "get": 403,
        "links": 403,
        "choices": 403,  # needs view on the target (folders)
        "post": True,
        "patch": 403,
        "delete": 403,
    },
    "deleter": {
        "list": 403,
        "get": 403,
        "links": True,
        "choices": 403,
        "post": 403,
        "patch": 403,
        "delete": True,
    },
}


@pytest.mark.parametrize("username", list(MATRIX))
@pytest.mark.parametrize(
    ("key", "route"),
    list(zip(["list", "get", "links", "choices", "post", "patch", "delete"], ROUTES, strict=True)),
)
async def test_route_matrix(
    sign_in: SignIn, db: AsyncEngine, username: str, key: str, route: tuple[str, str, Any]
) -> None:
    client = await sign_in(username)
    method, path, body = route
    response = await client.http.request(
        method, f"{API}{path}", json=body, headers=client._headers()
    )
    expected = MATRIX[username][key]
    if expected is True:
        assert response.status_code < 300, (username, key, response.text)
    else:
        assert response.status_code == expected, (username, key, response.text)
        assert _code(response) == "forbidden"
    async with AsyncSession(db) as session:
        doc = await session.get(Doc, 1)
        refused = expected is not True and method != "GET"
        if refused:  # nothing changed
            assert doc is not None
            assert doc.title == "open"


async def test_forbidden_writes_are_refused_before_the_body_is_read(sign_in: SignIn) -> None:
    viewer = await sign_in("viewer")
    response = await viewer.http.patch(
        f"{API}/models/docs/items/1", content=b"{not json", headers=viewer._headers()
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- object-level hooks


async def test_object_hooks_hide_and_lock_records(sign_in: SignIn) -> None:
    editor = await sign_in("editor")
    hidden = await editor.get("/models/docs/items/3")
    assert hidden.status_code == 404  # like a missing record: no existence oracle
    assert _code(hidden) == "not_found"
    locked = await editor.patch("/models/docs/items/2", {"title": "x"})
    assert locked.status_code == 403
    root = await sign_in("root")
    assert (await root.get("/models/docs/items/3")).status_code == 200
    deleter = await sign_in("deleter")
    assert (await deleter.delete("/models/docs/items/2")).status_code == 403
    assert (await deleter.delete("/models/docs/items/99")).status_code == 404


async def test_object_hooks_do_not_filter_lists(sign_in: SignIn) -> None:
    """Documented limitation: row visibility needs a list-query hook (v0.3)."""
    listed = (await (await sign_in("editor")).get("/models/docs/items")).json()
    assert {item["pk"] for item in listed["items"]} == {"1", "2", "3", "4"}


# --------------------------------------------------------------------------- related models (A1)


async def test_labels_of_hidden_targets_fall_back_to_the_key(sign_in: SignIn) -> None:
    blind = await sign_in("blind_editor")
    listed = (await blind.get("/models/docs/items")).json()
    assert listed["items"][0]["labels"] == {"folder_id": "1"}
    detail = (await blind.get("/models/docs/items/1")).json()
    assert detail["labels"] == {"folder_id": "1"}
    assert detail["many_labels"] == {"badges": {"1": "1"}}
    editor = await sign_in("editor")
    detail = (await editor.get("/models/docs/items/1")).json()
    assert detail["labels"] == {"folder_id": "Plans"}
    assert detail["many_labels"] == {"badges": {"1": "draft"}}


async def test_choices_need_view_on_the_target(sign_in: SignIn) -> None:
    blind = await sign_in("blind_editor")
    for field in ("folder_id", "badges"):
        response = await blind.get(f"/models/docs/fields/{field}/choices")
        assert response.status_code == 403, field
    assert (await blind.get("/models/docs/fields/nope/choices")).status_code == 404


@pytest.mark.parametrize(
    "body", [{"folder_id": 2}, {"folder_id": 999}, {"badges": [2]}, {"badges": [999]}]
)
async def test_relations_to_hidden_targets_are_readonly(
    sign_in: SignIn, body: dict[str, Any]
) -> None:
    """Existing or not, the answer is the same: no probe of a hidden model."""
    blind = await sign_in("blind_editor")
    response = await blind.patch("/models/docs/items/1", body)
    assert response.status_code == 422, response.text
    [issue] = response.json()["error"]["details"]
    assert (issue["loc"], issue["type"]) == ([next(iter(body))], "extra_forbidden")


async def test_link_counts_leave_out_hidden_models(sign_in: SignIn) -> None:
    root = await sign_in("root")
    counts = (await root.get("/models/badges/items/1/links")).json()["items"]
    assert counts == [{"identity": "docs", "field": "badges", "label": "Badges", "count": 1}]


# --------------------------------------------------------------------------- implications (A6)


async def test_create_without_view_returns_a_minimal_row(sign_in: SignIn) -> None:
    creator = await sign_in("creator")
    response = await creator.post("/models/docs/items", {"title": "blind", "level": 1})
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["data"] == {"title": "blind", "level": 1}
    assert row["labels"] == {}
    assert row["many_labels"] == {}
    assert row["truncated"] == []
    full = await (await sign_in("full_creator")).post("/models/docs/items", {"title": "seen"})
    assert set(full.json()["data"]) == {"id", "title", "level", "folder_id", "badges"}


async def test_delete_without_view(sign_in: SignIn, db: AsyncEngine) -> None:
    deleter = await sign_in("deleter")
    assert (await deleter.delete("/models/docs/items/4")).status_code == 204
    async with AsyncSession(db) as session:
        assert await session.get(Doc, 4) is None


async def test_extra_permissions_are_codenames(sign_in: SignIn, admin: Admin) -> None:
    assert "docs.publish" in admin._registry.codenames()
    assert admin._registry.codenames()[:4] == [
        "docs.view",
        "docs.create",
        "docs.edit",
        "docs.delete",
    ]


# --------------------------------------------------------------------------- query budget


class _Counter:
    def __init__(self, engine: AsyncEngine) -> None:
        self.count = 0
        event.listen(engine.sync_engine, "before_cursor_execute", self._hit)

    def _hit(self, *args: object) -> None:
        del args
        self.count += 1


@pytest.mark.parametrize(("username", "extra"), [("root", 1), ("viewer", 1)])
async def test_permissions_cost_one_query_per_request(
    sign_in: SignIn, db: AsyncEngine, username: str, extra: int
) -> None:
    """Resolution is one query, however many models, hooks or label lookups run."""
    client = await sign_in(username)
    counter = _Counter(db)
    await client.get("/models/folders/items")  # get_user + resolve + page + count
    assert counter.count == 1 + extra + 2
    counter.count = 0
    await client.get("/meta")  # get_user + resolve, hooks of 3 models cost nothing
    assert counter.count == 1 + extra


# --------------------------------------------------------------------------- route coverage


def _all_routes(routes: list[Any]) -> list[Any]:
    """Flatten routers included with `include_router` (FastAPI may nest them)."""
    flat: list[Any] = []
    for route in routes:
        nested = getattr(route, "original_router", None)
        flat.extend(_all_routes(list(nested.routes)) if nested is not None else [route])
    return flat


def _depends_on(dependant: Any, target: object) -> bool:
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


#: Routes without a model, which need only a session (the 401 test covers them).
SESSION_ONLY = {
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/auth/logout",
    "/api/v1/auth/password",  # one's own account only
}


def test_every_route_resolves_permissions(admin: Admin) -> None:
    """A new route cannot forget authorization: each must resolve permissions."""
    from faststudio.api._authz import resolve_permissions  # noqa: PLC0415

    checked = []
    for route in _all_routes(admin._sub_app.routes):
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in SESSION_ONLY:
            continue
        assert _depends_on(route.dependant, resolve_permissions), path
        checked.append(path)
    assert len(checked) >= 6
    assert "/api/v1/meta" in checked


# --------------------------------------------------------------------------- fail closed


async def test_hooks_must_return_true_to_allow(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def truthy(cls: type[ModelAdmin], request: Request, obj: object = None) -> Any:
        del cls, request, obj
        return "yes"  # truthy but not True: refused

    monkeypatch.setattr(DocAdmin, "has_view_permission", classmethod(truthy))
    root = await sign_in("root")
    assert (await root.get("/models/docs/items")).status_code == 403


async def test_a_broken_permission_backend_fails_closed(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = await sign_in("root")

    async def broken(self: PermBackend, session: AsyncSession, user: object) -> object:
        del self, session, user
        return {"docs.view"}  # a set, not a frozenset

    monkeypatch.setattr(PermBackend, "resolve", broken)
    with pytest.raises(TypeError, match="must return ALL or a frozenset"):
        await root.get("/models/docs/items")


async def test_guard_checks_run_on_create_too(
    sign_in: SignIn, db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creates now reach the account guard (`action="create"`); its post-write check counts."""
    from faststudio.auth.guard import FlagAccountGuard, WriteIntent, WriteRefused  # noqa: PLC0415

    seen: list[str] = []

    async def before_write(
        self: FlagAccountGuard, session: AsyncSession, user: object, intent: WriteIntent
    ) -> Any:
        del self, session, user
        seen.append(intent.action)

        async def refuse() -> None:
            raise WriteRefused("last_admin", "Refused after the flush.")

        return refuse

    monkeypatch.setattr(FlagAccountGuard, "before_write", before_write)
    monkeypatch.setattr(FlagAccountGuard, "guards", lambda self, model: True)
    root = await sign_in("root")
    response = await root.post("/models/docs/items", {"title": "never stored"})
    assert response.status_code == 409, response.text
    assert seen == ["create"]
    async with AsyncSession(db) as session:
        assert await session.scalar(select(func.count()).select_from(Doc)) == 4


async def test_writes_to_records_hidden_from_retrieve_are_404(sign_in: SignIn) -> None:
    """The object-level view hook applies to edit, delete and link counts too."""
    editor = await sign_in("editor")
    assert (await editor.patch("/models/docs/items/3", {})).status_code == 404
    curator = await sign_in("curator")
    assert (await curator.get("/models/docs/items/3/links")).status_code == 404
    assert (await curator.delete("/models/docs/items/3")).status_code == 404
    assert (await curator.delete("/models/docs/items/1")).status_code == 204
