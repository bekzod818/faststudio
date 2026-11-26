"""Many-to-many fields over the API (ADR-0010, M15).

Every test runs on SQLite with foreign keys enforced, on SQLite with
`PRAGMA foreign_keys` off (FastStudio's existence check is then the only
guard), and on PostgreSQL when FASTSTUDIO_TEST_POSTGRES_URL points at a
throwaway `*_test` database (the PostgreSQL CI job).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from faststudio import Admin, ModelAdmin, ModelUserBackend, hash_password
from faststudio.api import write as write_module
from tests._databases import MYSQL_URL, mysql_param, throwaway
from tests.factories.models import (
    AdminUser,
    Article,
    Base,
    Board,
    Label,
    Person,
    Post,
    Tag,
    Token,
    Topic,
    article_loose_topics,
    article_topics,
    board_labels,
    board_tokens,
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
        "labels",
        "tokens",
        "boards",
        "board_labels",
        "board_tokens",
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


class BoardAdmin(ModelAdmin, model=Board):
    list_display = ("id", "title")
    many_to_many = ("labels", "tokens")


class LabelAdmin(ModelAdmin, model=Label):
    list_display = ("code", "name")


class TokenAdmin(ModelAdmin, model=Token):
    list_display = ("uid", "name")


TOKEN_A = uuid.UUID("0f8fad5b-d9cb-469f-a165-70867728950e")
TOKEN_B = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


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
        *(
            pytest.param(
                kind,
                marks=[
                    pytest.mark.postgres,
                    pytest.mark.skipif(not POSTGRES_URL, reason="set FASTSTUDIO_TEST_POSTGRES_URL"),
                ],
            )
            for kind in ("postgres", "postgres-repeatable-read", "postgres-serializable")
        ),
        mysql_param("mysql"),  # InnoDB's default, REPEATABLE READ
        mysql_param("mysql-read-committed"),
    ]
)
def database(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    kind: str = request.param
    return kind


@pytest.fixture
async def db(database: str, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if database.startswith("postgres"):
        name = make_url(POSTGRES_URL).database or ""
        if not name.endswith("_test"):
            pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
        isolation = {
            "postgres": "READ COMMITTED",
            "postgres-repeatable-read": "REPEATABLE READ",
            "postgres-serializable": "SERIALIZABLE",
        }[database]
        engine = create_async_engine(POSTGRES_URL, isolation_level=isolation)
    elif database.startswith("mysql"):
        isolation = "READ COMMITTED" if database == "mysql-read-committed" else "REPEATABLE READ"
        engine = create_async_engine(throwaway(MYSQL_URL), isolation_level=isolation)
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
        session.add_all([Label(code="red", name="Red"), Label(code="blue", name="Blue")])
        session.add_all([Token(uid=TOKEN_A, name="alpha"), Token(uid=TOKEN_B, name="beta")])
        session.add(Board(id=1, title="board"))
        await session.flush()
        await session.execute(
            insert(post_tags), [{"post_id": 1, "tag_id": 1}, {"post_id": 1, "tag_id": 2}]
        )
        await session.execute(insert(follows), [{"follower_id": 1, "followed_id": 2}])
        await session.execute(
            insert(article_topics),
            [{"article_id": 1, "topic_id": 1}, {"article_id": 1, "topic_id": 2}],
        )
        if database.startswith("postgres"):  # explicit ids do not advance sequences
            for table in ("tags", "posts", "people", "topics", "articles", "boards"):
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
    for admin_class in (
        PostAdmin,
        TagAdmin,
        PersonAdmin,
        ArticleAdmin,
        BoardAdmin,
        LabelAdmin,
        TokenAdmin,
    ):
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


async def _links(db: AsyncEngine, table: Any, local: str, remote: str, pk: int) -> list[Any]:
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


async def test_link_counts_of_a_record_and_of_a_target(client: Client) -> None:
    """What a delete would remove, per field (M16, the delete confirmation)."""
    post = await client.get("/models/posts/items/1/links")
    assert post.status_code == 200, post.text
    assert post.json() == {
        "items": [{"identity": "posts", "field": "tags", "label": "Tags", "count": 2}]
    }
    tag = (await client.get("/models/tags/items/1/links")).json()
    assert tag == {"items": [{"identity": "posts", "field": "tags", "label": "Tags", "count": 1}]}
    unused = (await client.get("/models/tags/items/3/links")).json()
    assert unused["items"][0]["count"] == 0
    assert (await client.get("/models/labels/items/red/links")).json()["items"] == [
        {"identity": "boards", "field": "labels", "label": "Labels", "count": 0}
    ]


async def test_link_counts_match_what_delete_removes(client: Client, db: AsyncEngine) -> None:
    assert (await client.patch("/models/people/items/2", {"follows": [1, 3]})).status_code == 200
    counts = (await client.get("/models/people/items/2/links")).json()["items"]
    # Both directions of a self-referential field are one entry: 2 -> 1, 2 -> 3 and 1 -> 2.
    assert counts == [{"identity": "people", "field": "follows", "label": "Follows", "count": 3}]
    async with AsyncSession(db) as session:
        before = (await session.execute(select(func.count()).select_from(follows))).scalar_one()
    assert (await client.delete("/models/people/items/2")).status_code == 204
    async with AsyncSession(db) as session:
        after = (await session.execute(select(func.count()).select_from(follows))).scalar_one()
    assert before - after == 3


async def test_link_counts_list_every_opted_in_field(client: Client) -> None:
    """Fields sharing one association table are each listed (each loses its links)."""
    counts = (await client.get("/models/articles/items/1/links")).json()["items"]
    assert [(c["field"], c["count"]) for c in counts] == [
        ("topics", 2),
        ("seen_topics", 2),
        ("loose_topics", 0),
    ]
    assert (await client.get("/models/boards/items/1/links")).json()["items"] == [
        {"identity": "boards", "field": "labels", "label": "Labels", "count": 0},
        {"identity": "boards", "field": "tokens", "label": "Tokens", "count": 0},
    ]


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/models/posts/items/99/links", 404),
        ("/models/posts/items/not-a-key/links", 404),
        ("/models/nope/items/1/links", 404),
    ],
)
async def test_link_counts_of_missing_records(client: Client, path: str, status: int) -> None:
    assert (await client.get(path)).status_code == status


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
    database: str,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, Any, str, str],
) -> None:
    path, field, table, local, remote = case
    first, second = await sign_in(), await sign_in()
    barrier = asyncio.Barrier(2)
    current_links = write_module._current_links

    async def synchronized(*args: Any, **kwargs: Any) -> Any:
        await barrier.wait()  # both requests validated, both about to lock and write
        return await current_links(*args, **kwargs)

    monkeypatch.setattr(write_module, "_current_links", synchronized)
    results = await asyncio.gather(
        first.patch(path, {field: [1]}), second.patch(path, {field: [1]})
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses in ([200, 200], [200, 409]), [r.text for r in results]
    assert (await first.get(path)).json()["data"][field] == [1]  # and reads are DISTINCT
    pk = int(path.rsplit("/", 1)[1])
    stored = await _links(db, table, local, remote, pk)
    if database == "postgres-repeatable-read":
        # Documented limitation: the second writer's snapshot is stale, so without
        # a unique pair a duplicate row can be stored (reads hide it).
        assert stored in ([1], [1, 1])
    else:
        # The record lock serializes both writes: one pair is stored, even without
        # a unique constraint on the association table.
        assert stored == [1]


async def test_concurrent_replaces_never_merge(
    sign_in: Callable[[], Awaitable[Client]],
    db: AsyncEngine,
    database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = await sign_in(), await sign_in()
    barrier = asyncio.Barrier(2)
    current_links = write_module._current_links

    async def synchronized(*args: Any, **kwargs: Any) -> Any:
        await barrier.wait()
        return await current_links(*args, **kwargs)

    monkeypatch.setattr(write_module, "_current_links", synchronized)
    results = await asyncio.gather(
        first.patch("/models/posts/items/2", {"tags": [1, 2]}),
        second.patch("/models/posts/items/2", {"tags": [3]}),
    )
    assert all(r.status_code in {200, 409} for r in results), [r.text for r in results]
    assert any(r.status_code == 200 for r in results)
    stored = await _links(db, post_tags, "post_id", "tag_id", 2)
    if database == "postgres-repeatable-read":
        assert stored in ([1, 2], [3], [1, 2, 3])  # documented: may merge under PG RR
    else:
        assert stored in ([1, 2], [3])  # one request's set, never the union


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


# --------------------------------------------------------------------------- key types


async def test_string_and_uuid_keys(client: Client, db: AsyncEngine) -> None:
    upper = str(TOKEN_B).upper()  # any case is accepted for a UUID
    response = await client.patch(
        "/models/boards/items/1", {"labels": ["red", "blue"], "tokens": [upper, str(TOKEN_A)]}
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["data"]["labels"] == ["blue", "red"]
    assert row["data"]["tokens"] == sorted([str(TOKEN_A), str(TOKEN_B)])
    assert row["many_labels"] == {
        "labels": {"blue": "Blue", "red": "Red"},
        "tokens": {str(TOKEN_A): "alpha", str(TOKEN_B): "beta"},
    }
    assert await _links(db, board_labels, "board_id", "label_code", 1) == ["blue", "red"]
    replaced = await client.patch("/models/boards/items/1", {"labels": ["red"], "tokens": []})
    assert replaced.json()["data"]["labels"] == ["red"]
    assert await _links(db, board_tokens, "board_id", "token_uid", 1) == []
    unknown = await client.patch("/models/boards/items/1", {"labels": ["green"]})
    assert (["labels"], "foreign_key") in _issues(unknown)
    not_a_uuid = await client.patch("/models/boards/items/1", {"tokens": ["nope"]})
    assert unknown.status_code == not_a_uuid.status_code == 422


# --------------------------------------------------------------------------- triggers


_TRIGGERS = {
    "postgres": [
        "CREATE TABLE post_update_audit (n integer NOT NULL)",
        "CREATE FUNCTION fs_test_count_post_updates() RETURNS trigger AS $$ "
        "BEGIN INSERT INTO post_update_audit VALUES (1); RETURN NEW; END $$ LANGUAGE plpgsql",
        "CREATE TRIGGER fs_test_post_updates AFTER UPDATE ON posts "
        "FOR EACH ROW EXECUTE FUNCTION fs_test_count_post_updates()",
    ],
    "sqlite": [
        "CREATE TABLE post_update_audit (n integer NOT NULL)",
        "CREATE TRIGGER fs_test_post_updates AFTER UPDATE ON posts "
        "BEGIN INSERT INTO post_update_audit VALUES (1); END",
    ],
    "mysql": [
        "CREATE TABLE post_update_audit (n integer NOT NULL)",
        "CREATE TRIGGER fs_test_post_updates AFTER UPDATE ON posts "
        "FOR EACH ROW INSERT INTO post_update_audit VALUES (1)",
    ],
}
_DROP = {
    "postgres": [
        "DROP TRIGGER IF EXISTS fs_test_post_updates ON posts",
        "DROP FUNCTION IF EXISTS fs_test_count_post_updates()",
        "DROP TABLE IF EXISTS post_update_audit",
    ],
    "mysql": [
        "DROP TRIGGER IF EXISTS fs_test_post_updates",
        "DROP TABLE IF EXISTS post_update_audit",
    ],
    "sqlite": [
        "DROP TRIGGER IF EXISTS fs_test_post_updates",
        "DROP TABLE IF EXISTS post_update_audit",
    ],
}


async def _audit_count(db: AsyncEngine) -> int:
    async with db.connect() as conn:
        count: int = (
            await conn.execute(text("SELECT count(*) FROM post_update_audit"))
        ).scalar_one()
    return count


async def test_links_only_write_never_updates_the_record_row(
    client: Client, db: AsyncEngine, database: str
) -> None:
    """Host `ON UPDATE` triggers must not fire when only links change (PostgreSQL/MySQL).

    SQLite has no `SELECT ... FOR UPDATE`, so FastStudio takes its write lock
    with a no-change UPDATE there, and the trigger fires once (documented).
    """
    kind = next((k for k in ("postgres", "mysql") if database.startswith(k)), "sqlite")
    try:
        async with db.begin() as conn:
            for statement in _TRIGGERS[kind]:
                await conn.execute(text(statement))
        response = await client.patch("/models/posts/items/1", {"tags": [3]})
        assert response.status_code == 200, response.text
        assert await _audit_count(db) == (1 if kind == "sqlite" else 0)
        before = await _audit_count(db)
        await client.patch("/models/posts/items/1", {"title": "renamed"})
        assert await _audit_count(db) == before + 1  # the trigger itself works
    finally:
        async with db.begin() as conn:
            for statement in _DROP[kind]:
                await conn.execute(text(statement))


# --------------------------------------------------------------------------- session factories


async def test_session_factory_with_binds_only(
    app: FastAPI, db: AsyncEngine, secret_key: str
) -> None:
    """A host factory routing engines only through `binds=` (no default bind) works."""
    maker = async_sessionmaker(binds={Base: db}, expire_on_commit=False)
    instance = Admin(
        app,
        session_maker=maker,
        auth_backend=ModelUserBackend(AdminUser),
        secret_key=secret_key,
    )
    instance.register(PostAdmin)
    instance.register(TagAdmin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:
        await http.get(f"{API}/auth/me")
        login = await http.post(
            f"{API}/auth/login",
            json={"username": "admin", "password": PASSWORD},
            headers={"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN},
        )
        assert login.status_code == 200, login.text
        headers = {"x-faststudio-csrf": http.cookies["faststudio_csrftoken"], "origin": ORIGIN}
        detail = await http.get(f"{API}/models/posts/items/1")
        assert detail.json()["data"]["tags"] == [1, 2]
        replaced = await http.patch(
            f"{API}/models/posts/items/1", json={"tags": [3]}, headers=headers
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["data"]["tags"] == [3]
        created = await http.post(
            f"{API}/models/posts/items", json={"title": "new", "tags": [1, 3]}, headers=headers
        )
        assert created.status_code == 201, created.text
        new_pk = int(created.json()["pk"])
        counts = await http.get(f"{API}/models/tags/items/3/links")
        assert counts.json()["items"][0]["count"] == 2
        tag_deleted = await http.delete(f"{API}/models/tags/items/3", headers=headers)
        assert tag_deleted.status_code == 204, tag_deleted.text
        deleted = await http.delete(f"{API}/models/posts/items/1", headers=headers)
        assert deleted.status_code == 204, deleted.text
    assert await _links(db, post_tags, "post_id", "tag_id", 1) == []
    assert await _links(db, post_tags, "post_id", "tag_id", new_pk) == [1]
