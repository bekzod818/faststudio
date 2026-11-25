"""Many-to-many fields over the API (ADR-0010, M15).

Every test runs on SQLite with foreign keys enforced, on SQLite with
`PRAGMA foreign_keys` off (FastStudio's existence check is then the only
guard), and on PostgreSQL when FASTSTUDIO_TEST_POSTGRES_URL points at a
throwaway `*_test` database (the PostgreSQL CI job).
"""

from __future__ import annotations

import asyncio
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

from faststudio import Admin, ModelAdmin, ModelUserBackend, hash_password
from faststudio.api import write as write_module
from tests.factories.models import (
    AdminUser,
    Article,
    Base,
    Person,
    Post,
    Tag,
    Topic,
    article_loose_topics,
    article_topics,
    follows,
    post_tags,
)

ORIGIN = "https://testserver"
API = "/admin/api/v1"
PASSWORD = "a long test passphrase"
TABLES = [
    Base.metadata.tables[name]
    for name in (
        "admin_users",
        "tags",
        "posts",
        "post_tags",
        "people",
        "follows",
        "topics",
        "articles",
        "article_topics",
        "article_loose_topics",
        "article_weighted_topics",
    )
]
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")


class PostAdmin(ModelAdmin, model=Post):
    list_display = ("id", "title")
    many_to_many = ("tags",)


class TagAdmin(ModelAdmin, model=Tag):
    list_display = ("id", "label")


class PersonAdmin(ModelAdmin, model=Person):
    list_display = ("id", "name")
    many_to_many = ("follows",)


class ArticleAdmin(ModelAdmin, model=Article):
    """`Topic` is deliberately not registered: labels fall back to the key."""

    list_display = ("id", "title")
    many_to_many = ("topics", "seen_topics", "loose_topics")
    many_to_many_limits = {"topics": 1}  # noqa: RUF012 - a ModelAdmin option


# --------------------------------------------------------------------------- database


@pytest.fixture(
    params=[
        "sqlite-fk-on",
        "sqlite-fk-off",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
            ],
        ),
    ]
)
def database(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    kind: str = request.param
    return kind if kind != "postgres" else POSTGRES_URL and kind  # skipif guards the empty URL


@pytest.fixture
async def db(database: str, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if database == "postgres":
        name = make_url(POSTGRES_URL).database or ""
        if not name.endswith("_test"):
            pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
        engine = create_async_engine(POSTGRES_URL)
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m2m.db")
        pragma = "ON" if database == "sqlite-fk-on" else "OFF"

        @event.listens_for(engine.sync_engine, "connect")
        def _foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.execute(f"PRAGMA foreign_keys={pragma}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, tables=TABLES)
        await conn.run_sync(Base.metadata.create_all, tables=TABLES)
    async with AsyncSession(engine) as session:
        session.add(
            AdminUser(username="admin", password_hash=hash_password(PASSWORD), is_admin=True)
        )
        session.add_all(
            [Tag(id=i, label=label) for i, label in [(1, "news"), (2, "tech"), (3, "")]]
        )
        session.add_all([Topic(id=1, name="a"), Topic(id=2, name="b")])
        session.add_all([Person(id=i, name=f"p{i}") for i in (1, 2, 3)])
        session.add_all([Post(id=1, title="tagged"), Post(id=2, title="plain")])
        session.add(Article(id=1, title="many topics"))
        await session.flush()
        await session.execute(
            insert(post_tags), [{"post_id": 1, "tag_id": 1}, {"post_id": 1, "tag_id": 2}]
        )
        await session.execute(insert(follows), [{"follower_id": 1, "followed_id": 2}])
        await session.execute(
            insert(article_topics),
            [{"article_id": 1, "topic_id": 1}, {"article_id": 1, "topic_id": 2}],
        )
        if database == "postgres":  # explicit ids do not advance PostgreSQL sequences
            for table in ("tags", "posts", "people", "topics", "articles"):
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
            await conn.run_sync(Base.metadata.drop_all, tables=TABLES)
        await engine.dispose()


@pytest.fixture
def admin(app: FastAPI, db: AsyncEngine, secret_key: str) -> Admin:
    instance = Admin(
        app, engine=db, auth_backend=ModelUserBackend(AdminUser), secret_key=secret_key
    )
    for admin_class in (PostAdmin, TagAdmin, PersonAdmin, ArticleAdmin):
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


@pytest.fixture
async def sign_in(app: FastAPI, admin: Admin) -> AsyncIterator[Callable[[], Awaitable[Client]]]:
    del admin  # mounted
    async with AsyncExitStack() as stack:

        async def _sign_in() -> Client:
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
            )
            await http.get(f"{API}/auth/me")
            token = http.cookies["faststudio_csrftoken"]
            response = await http.post(
                f"{API}/auth/login",
                json={"username": "admin", "password": PASSWORD},
                headers={"x-faststudio-csrf": token, "origin": ORIGIN},
            )
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


@pytest.fixture
async def client(sign_in: Callable[[], Awaitable[Client]]) -> Client:
    return await sign_in()


async def _links(db: AsyncEngine, table: Any, local: str, remote: str, pk: int) -> list[int]:
    async with AsyncSession(db) as session:
        rows = await session.execute(
            select(table.c[remote]).where(table.c[local] == pk).order_by(table.c[remote])
        )
    return [row[0] for row in rows]


def _issues(response: httpx.Response) -> list[tuple[list[Any], str]]:
    body = response.json()["error"]
    assert body["code"] == "validation_error", body
    return [(issue["loc"], issue["type"]) for issue in body["details"]]


# --------------------------------------------------------------------------- meta and read


async def test_meta_describes_many_to_many_fields(client: Client) -> None:
    meta = (await client.get("/meta")).json()
    posts = next(m for m in meta["models"] if m["identity"] == "posts")
    tags = posts["fields"][-1]  # after the column fields
    assert tags == {
        **tags,
        "name": "tags",
        "label": "Tags",
        "type": "many_to_many",
        "nullable": False,
        "required": False,
        "readonly": False,
        "default": [],
        "max_items": 500,
        "relation": {"target_identity": "tags", "target_field": "id", "value_type": "integer"},
    }
    assert all(field["max_items"] is None for field in posts["fields"][:-1])
    articles = next(m for m in meta["models"] if m["identity"] == "articles")
    by_name = {field["name"]: field for field in articles["fields"]}
    assert by_name["seen_topics"]["readonly"] is True  # viewonly relationship
    assert by_name["topics"]["max_items"] == 1
    assert by_name["topics"]["relation"]["target_identity"] is None  # Topic not registered


async def test_detail_row_has_keys_labels_and_truncation(client: Client) -> None:
    post = (await client.get("/models/posts/items/1")).json()
    assert post["data"]["tags"] == [1, 2]
    assert post["many_labels"] == {"tags": {"1": "news", "2": "tech"}}
    assert post["truncated"] == []

    article = (await client.get("/models/articles/items/1")).json()
    assert article["data"]["topics"] == [1]  # limit 1, two links exist
    assert article["truncated"] == ["topics"]
    assert article["many_labels"]["topics"] == {"1": "1"}  # target not registered: the key
    assert article["data"]["seen_topics"] == [1, 2]
    assert article["data"]["loose_topics"] == []


async def test_lists_never_include_many_to_many(client: Client) -> None:
    listed = (await client.get("/models/posts/items")).json()
    for row in listed["items"]:
        assert "tags" not in row["data"]
        assert (row["many_labels"], row["truncated"]) == ({}, [])


async def test_choices_for_a_many_to_many_field(client: Client) -> None:
    choices = (await client.get("/models/posts/fields/tags/choices")).json()
    assert [item["value"] for item in choices["items"]] == ["3", "1", "2"]  # by label, "" first
    assert (await client.get("/models/articles/fields/topics/choices")).status_code == 404


# --------------------------------------------------------------------------- write


async def test_create_with_keys(client: Client, db: AsyncEngine) -> None:
    created = await client.post("/models/posts/items", {"title": "new", "tags": [3, 1]})
    assert created.status_code == 201, created.text
    pk = int(created.json()["pk"])
    assert created.json()["data"]["tags"] == [1, 3]
    assert await _links(db, post_tags, "post_id", "tag_id", pk) == [1, 3]


async def test_update_replaces_the_set(client: Client, db: AsyncEngine) -> None:
    replaced = await client.patch("/models/posts/items/1", {"tags": [2, 3]})
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["data"]["tags"] == [2, 3]
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == [2, 3]
    cleared = await client.patch("/models/posts/items/1", {"tags": []})
    assert cleared.json()["data"]["tags"] == []
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == []


async def test_self_referential_update(client: Client, db: AsyncEngine) -> None:
    response = await client.patch("/models/people/items/1", {"follows": [2, 3]})
    assert response.status_code == 200, response.text
    assert await _links(db, follows, "follower_id", "followed_id", 1) == [2, 3]


@pytest.mark.parametrize(
    ("path", "body", "issue"),
    [
        ("/models/posts/items/1", {"tags": [1, 99]}, (["tags"], "foreign_key")),
        ("/models/posts/items/1", {"tags": [1, 1]}, (["tags"], "value_error")),
        ("/models/posts/items/1", {"tags": None}, (["tags"], "list_type")),
        ("/models/posts/items/1", {"tags": ["x"]}, (["tags", 0], "int_type")),
        ("/models/articles/items/1", {"seen_topics": [1]}, (["seen_topics"], "extra_forbidden")),
        ("/models/articles/items/1", {"topics": [1]}, (["topics"], "truncated")),
        (
            "/models/people/items/1",
            {"follows": list(range(1, 502))},
            (["follows"], "too_long"),
        ),
    ],
)
async def test_invalid_writes_are_refused(
    client: Client, db: AsyncEngine, path: str, body: dict[str, Any], issue: tuple[list[Any], str]
) -> None:
    before = await _links(db, post_tags, "post_id", "tag_id", 1)
    response = await client.patch(path, body)
    assert response.status_code == 422, response.text
    assert issue in _issues(response)
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == before


async def test_create_with_unknown_key_writes_nothing(client: Client, db: AsyncEngine) -> None:
    response = await client.post("/models/posts/items", {"title": "x", "tags": [99]})
    assert response.status_code == 422
    async with AsyncSession(db) as session:
        assert await session.scalar(select(func.count()).select_from(Post)) == 2


async def test_failed_link_write_rolls_back_everything(
    client: Client, db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database error while inserting links undoes the column change and the deletes."""

    def duplicate_pair(link: Any, pk: object, keys: Any) -> Any:
        # (1, 1) is still linked after tag 2 was removed: a duplicate pair.
        return insert(link.secondary).values({link.local_fk.key: pk, link.remote_fk.key: 1})

    monkeypatch.setattr(write_module, "insert_links_statement", duplicate_pair)
    response = await client.patch("/models/posts/items/1", {"title": "changed", "tags": [1, 3]})
    assert response.status_code == 409, response.text  # IntegrityError -> conflict, never 500
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == [1, 2]
    async with AsyncSession(db) as session:
        assert (await session.get(Post, 1)).title == "tagged"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- delete


async def test_delete_removes_own_links(client: Client, db: AsyncEngine) -> None:
    assert (await client.delete("/models/posts/items/1")).status_code == 204
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == []


async def test_delete_of_a_target_removes_links_pointing_at_it(
    client: Client, db: AsyncEngine
) -> None:
    assert (await client.delete("/models/tags/items/1")).status_code == 204
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == [2]


async def test_self_referential_delete_removes_both_directions(
    client: Client, db: AsyncEngine
) -> None:
    assert (await client.patch("/models/people/items/2", {"follows": [3]})).status_code == 200
    assert (await client.delete("/models/people/items/2")).status_code == 204
    assert await _links(db, follows, "follower_id", "followed_id", 1) == []
    assert await _links(db, follows, "follower_id", "followed_id", 2) == []


# --------------------------------------------------------------------------- concurrency


@pytest.mark.parametrize(
    "case",
    [
        ("/models/posts/items/2", "tags", post_tags, "post_id", "tag_id"),  # unique pair
        (
            "/models/articles/items/1",
            "loose_topics",
            article_loose_topics,
            "article_id",
            "topic_id",
        ),
    ],
)
async def test_concurrent_identical_adds_never_fail_or_duplicate(
    sign_in: Callable[[], Awaitable[Client]],
    db: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, Any, str, str],
) -> None:
    path, field, table, local, remote = case
    first, second = await sign_in(), await sign_in()
    barrier = asyncio.Barrier(2)
    replace_many = write_module._replace_many

    async def synchronized(*args: Any, **kwargs: Any) -> None:
        await barrier.wait()  # both requests validated, both about to write
        await replace_many(*args, **kwargs)

    monkeypatch.setattr(write_module, "_replace_many", synchronized)
    results = await asyncio.gather(
        first.patch(path, {field: [1]}), second.patch(path, {field: [1]})
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses in ([200, 200], [200, 409]), [r.text for r in results]
    shown = (await first.get(path.removeprefix(API))).json()["data"][field]
    assert shown == [1]  # DISTINCT: duplicates never reach the API
    pk = int(path.rsplit("/", 1)[1])
    assert set(await _links(db, table, local, remote, pk)) == {1}


# --------------------------------------------------------------------------- bounds


async def test_ten_thousand_keys_round_trip_in_chunks(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    """Large sets stay below the bound-parameter limits (500 keys per statement)."""
    async with AsyncSession(db) as session:
        await session.execute(insert(Tag), [{"id": i, "label": f"t{i}"} for i in range(10, 10_010)])
        await session.commit()

    class BigPostAdmin(ModelAdmin, model=Post):
        identity = "bigposts"
        list_display = ("id", "title")
        many_to_many = ("tags",)
        many_to_many_limits = {"tags": 10_000}  # noqa: RUF012

    instance = Admin(
        app, engine=db, auth_backend=ModelUserBackend(AdminUser), secret_key=secret_key
    )
    instance.register(BigPostAdmin)
    instance.register(TagAdmin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:
        await http.get(f"{API}/auth/me")
        token = http.cookies["faststudio_csrftoken"]
        login = await http.post(
            f"{API}/auth/login",
            json={"username": "admin", "password": PASSWORD},
            headers={"x-faststudio-csrf": token, "origin": ORIGIN},
        )
        assert login.status_code == 200
        keys = list(range(10, 10_010))
        response = await http.patch(
            f"{API}/models/bigposts/items/2",
            json={"tags": keys},
            headers={"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN},
        )
        assert response.status_code == 200, response.text[:300]
        row = response.json()
        assert row["data"]["tags"] == keys
        assert len(row["many_labels"]["tags"]) == 10_000
        assert row["many_labels"]["tags"]["10009"] == "t10009"
        assert row["truncated"] == []
