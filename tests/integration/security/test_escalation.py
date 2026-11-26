"""Escalation rules (ADR-0011 §6, A2; threat model T9; M17).

`manager` may manage users, groups and permissions but holds only `docs.view`
and `docs.edit` among the content permissions, so every write that would give
anyone `docs.delete` (or any other codename they lack) must be refused,
whichever side of a relationship it comes from. Runs on SQLite and, with
FASTSTUDIO_TEST_POSTGRES_URL, on PostgreSQL.
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
from sqlalchemy import insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from faststudio import Admin, ModelAdmin, hash_password
from tests._databases import MYSQL_URL, mysql_param, throwaway
from tests.factories.auth_models import (
    AuthBase,
    AuthGroup,
    AuthPermission,
    AuthUser,
    PermBackend,
    group_permissions,
    user_groups,
    user_permissions,
)

ORIGIN = "https://testserver"
API = "/admin/api/v1"
PASSWORD = "a long test passphrase"
POSTGRES_URL = os.environ.get("FASTSTUDIO_TEST_POSTGRES_URL", "")


class UserAdmin(ModelAdmin, model=AuthUser):
    identity = "users"
    list_display = ("id", "username")
    exclude = ("password_hash",)
    many_to_many = ("groups", "permissions")


class GroupAdmin(ModelAdmin, model=AuthGroup):
    identity = "groups"
    list_display = ("id", "name")
    many_to_many = ("permissions", "users")


class PermissionAdmin(ModelAdmin, model=AuthPermission):
    identity = "permissions"
    list_display = ("id", "codename")
    many_to_many = ("groups", "users")


MANAGE = [
    f"{m}.{a}" for m in ("users", "groups", "permissions") for a in ("view", "create", "edit")
]
CODENAMES = [*MANAGE, "docs.view", "docs.edit", "docs.delete", "docs.publish"]
P = {codename: index for index, codename in enumerate(CODENAMES, 1)}

# Users: id -> (username, superuser, direct codenames).
ROOT, MANAGER, ALICE, SU2, HOLDER = 1, 2, 3, 4, 5
USERS: dict[int, tuple[str, bool, list[str]]] = {
    ROOT: ("root", True, []),
    MANAGER: ("manager", False, [*MANAGE, "docs.view", "docs.edit"]),
    ALICE: ("alice", False, []),
    SU2: ("su2", True, []),
    HOLDER: ("holder", False, ["docs.edit", "docs.delete"]),  # already holds what writers grant
}
# Groups: id -> (name, codenames).
READERS, WRITERS = 1, 2
GROUPS = {READERS: ("readers", ["docs.view"]), WRITERS: ("writers", ["docs.edit", "docs.delete"])}


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
        mysql_param("mysql"),
    ]
)
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    if request.param == "postgres":
        name = make_url(POSTGRES_URL).database or ""
        if not name.endswith("_test"):
            pytest.fail(f"Refusing to drop tables in {name!r}: use a database named *_test.")
        engine = create_async_engine(POSTGRES_URL)
    elif request.param == "mysql":
        engine = create_async_engine(throwaway(MYSQL_URL))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/escalation.db")
    async with engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.drop_all)
        await conn.run_sync(AuthBase.metadata.create_all)
    password_hash = hash_password(PASSWORD)
    async with AsyncSession(engine) as session:
        session.add_all(AuthPermission(id=i, codename=c) for c, i in P.items())
        session.add_all(
            AuthUser(id=pk, username=name, password_hash=password_hash, is_superuser=su)
            for pk, (name, su, _) in USERS.items()
        )
        session.add_all(AuthGroup(id=pk, name=name) for pk, (name, _) in GROUPS.items())
        await session.flush()
        await session.execute(
            insert(user_permissions),
            [
                {"user_id": pk, "permission_id": P[c]}
                for pk, (_, _, cs) in USERS.items()
                for c in cs
            ],
        )
        await session.execute(
            insert(group_permissions),
            [{"group_id": pk, "permission_id": P[c]} for pk, (_, cs) in GROUPS.items() for c in cs],
        )
        if request.param == "postgres":
            for table in ("t_users", "t_groups", "t_permissions"):
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
    for admin_class in (UserAdmin, GroupAdmin, PermissionAdmin):
        instance.register(admin_class)
    return instance


class Client:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {"x-faststudio-csrf": self.http.cookies["faststudio_csrftoken"], "origin": ORIGIN}

    async def post(self, path: str, body: object) -> httpx.Response:
        return await self.http.post(f"{API}{path}", json=body, headers=self._headers())

    async def patch(self, path: str, body: object) -> httpx.Response:
        return await self.http.patch(f"{API}{path}", json=body, headers=self._headers())

    async def delete(self, path: str) -> httpx.Response:
        return await self.http.delete(f"{API}{path}", headers=self._headers())


SignIn = Callable[[str], Awaitable[Client]]


@pytest.fixture
async def sign_in(app: FastAPI, admin: Admin) -> AsyncIterator[SignIn]:
    del admin
    async with AsyncExitStack() as stack:

        async def _sign_in(username: str) -> Client:
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN)
            )
            await http.get(f"{API}/auth/me")
            token = http.cookies["faststudio_csrftoken"]
            response = await http.post(
                f"{API}/auth/login",
                json={"username": username, "password": PASSWORD},
                headers={"x-faststudio-csrf": token, "origin": ORIGIN},
            )
            assert response.status_code == 200, response.text
            return Client(http)

        yield _sign_in


async def _codenames_of(db: AsyncEngine, user: int) -> set[str]:
    backend = PermBackend()
    async with AsyncSession(db) as session:
        perms = (await backend.resolve_accounts(session, [user])).get(user, frozenset())
    assert isinstance(perms, frozenset)
    return set(perms)


async def _group_ids(db: AsyncEngine, user: int) -> list[int]:
    async with AsyncSession(db) as session:
        rows = await session.scalars(
            select(user_groups.c.group_id).where(user_groups.c.user_id == user)
        )
        return sorted(rows)


# --------------------------------------------------------------------------- every path

#: (description, method, path, body, allowed for manager). Root may do all of them.
CASES: list[tuple[str, str, str, dict[str, Any], bool]] = [
    # user.permissions
    (
        "grant a held codename",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"permissions": [P["docs.view"]]},
        True,
    ),
    (
        "grant an unheld codename",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"permissions": [P["docs.delete"]]},
        False,
    ),
    # user.groups
    (
        "join a group within the actor's",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"groups": [READERS]},
        True,
    ),
    (
        "join a group beyond the actor's",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"groups": [WRITERS]},
        False,
    ),
    (
        "self-membership beyond the actor's",
        "PATCH",
        f"/models/users/items/{MANAGER}",
        {"groups": [WRITERS]},
        False,
    ),
    (
        "join a group granting nothing new",
        "PATCH",
        f"/models/users/items/{HOLDER}",
        {"groups": [WRITERS]},
        True,
    ),
    # group.permissions (every member is affected, the actor included)
    (
        "group gains a held codename",
        "PATCH",
        f"/models/groups/items/{READERS}",
        {"permissions": [P["docs.view"], P["docs.edit"]]},
        True,
    ),
    (
        "group gains an unheld codename",
        "PATCH",
        f"/models/groups/items/{READERS}",
        {"permissions": [P["docs.view"], P["docs.publish"]]},
        False,
    ),
    # group.users (reverse side of user.groups)
    (
        "add a user to a group within the actor's",
        "PATCH",
        f"/models/groups/items/{READERS}",
        {"users": [ALICE]},
        True,
    ),
    (
        "add a user to a group beyond the actor's",
        "PATCH",
        f"/models/groups/items/{WRITERS}",
        {"users": [ALICE]},
        False,
    ),
    (
        "add a user who holds it all already",
        "PATCH",
        f"/models/groups/items/{WRITERS}",
        {"users": [HOLDER]},
        True,
    ),
    # permission.groups / permission.users (reverse sides)
    (
        "give a held permission to a group",
        "PATCH",
        f"/models/permissions/items/{P['docs.view']}",
        {"groups": [WRITERS]},
        True,
    ),
    (
        "give an unheld permission to a group",
        "PATCH",
        f"/models/permissions/items/{P['docs.publish']}",
        {"groups": [READERS]},
        False,
    ),
    (
        "give a held permission to a user",
        "PATCH",
        f"/models/permissions/items/{P['docs.edit']}",
        {"users": [ALICE]},
        True,
    ),
    (
        "give an unheld permission to a user",
        "PATCH",
        f"/models/permissions/items/{P['docs.delete']}",
        {"users": [ALICE]},
        False,
    ),
    # renaming a permission gives its holders the new codename
    (
        "rename to an unheld codename",
        "PATCH",
        f"/models/permissions/items/{P['docs.view']}",
        {"codename": "docs.export"},
        False,
    ),
    (
        "rename to the same codename",
        "PATCH",
        f"/models/permissions/items/{P['docs.view']}",
        {"codename": "docs.view"},
        True,
    ),
    # the superuser-like flag and accounts holding ALL
    (
        "make someone a superuser",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"is_superuser": True},
        False,
    ),
    (
        "send the flag unchanged",
        "PATCH",
        f"/models/users/items/{ALICE}",
        {"is_superuser": False},
        True,
    ),
    ("edit a superuser", "PATCH", f"/models/users/items/{SU2}", {"username": "renamed"}, False),
    # creates follow the same rules
    (
        "create a superuser",
        "POST",
        "/models/users/items",
        {"username": "new", "is_superuser": True},
        False,
    ),
    (
        "create a user in a group beyond the actor's",
        "POST",
        "/models/users/items",
        {"username": "new", "groups": [WRITERS]},
        False,
    ),
    (
        "create a user in a group within the actor's",
        "POST",
        "/models/users/items",
        {"username": "new", "groups": [READERS]},
        True,
    ),
    (
        "create a group with an unheld codename",
        "POST",
        "/models/groups/items",
        {"name": "g", "permissions": [P["docs.delete"]]},
        False,
    ),
    (
        "create a group with held codenames",
        "POST",
        "/models/groups/items",
        {"name": "g", "permissions": [P["docs.edit"]], "users": [ALICE]},
        True,
    ),
    (
        "create an unheld permission for a group",
        "POST",
        "/models/permissions/items",
        {"codename": "x.y", "groups": [READERS]},
        False,
    ),
    (
        "create an unheld permission for nobody",
        "POST",
        "/models/permissions/items",
        {"codename": "x.y"},
        True,
    ),
    # removals never escalate
    (
        "remove a group's permissions",
        "PATCH",
        f"/models/groups/items/{WRITERS}",
        {"permissions": []},
        True,
    ),
    (
        "remove a user's permissions",
        "PATCH",
        f"/models/users/items/{HOLDER}",
        {"permissions": []},
        True,
    ),
]


@pytest.mark.parametrize(
    ("method", "path", "body", "allowed"),
    [pytest.param(*case[1:], id=case[0]) for case in CASES],
)
async def test_manager_cannot_grant_more_than_they_hold(
    sign_in: SignIn, db: AsyncEngine, method: str, path: str, body: dict[str, Any], *, allowed: bool
) -> None:
    before = {user: await _codenames_of(db, user) for user in (ALICE, MANAGER, HOLDER)}
    manager = await sign_in("manager")
    response = await manager.http.request(
        method, f"{API}{path}", json=body, headers=manager._headers()
    )
    if allowed:
        assert response.status_code in {200, 201}, response.text
        return
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"
    after = {user: await _codenames_of(db, user) for user in (ALICE, MANAGER, HOLDER)}
    assert after == before  # rolled back: nobody gained anything


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [pytest.param(*case[1:4], id=case[0]) for case in CASES if not case[4]],
)
async def test_root_may_do_all_of_it(
    sign_in: SignIn, method: str, path: str, body: dict[str, Any]
) -> None:
    root = await sign_in("root")
    response = await root.http.request(method, f"{API}{path}", json=body, headers=root._headers())
    assert response.status_code in {200, 201}, response.text


async def test_superuser_accounts_are_off_limits(sign_in: SignIn) -> None:
    manager = await sign_in("manager")
    assert (await manager.delete(f"/models/users/items/{SU2}")).status_code == 403
    root = await sign_in("root")
    assert (await root.delete(f"/models/users/items/{SU2}")).status_code == 204


@pytest.mark.parametrize(
    ("method", "body"),
    [("patch", {"is_active": False}), ("patch", {"username": "x"}), ("delete", None)],
)
async def test_a_promotion_committed_meanwhile_is_seen(
    sign_in: SignIn,
    db: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    body: object,
) -> None:
    """Alice becomes a superuser after the manager's request loaded her, before the
    lock: the write must still be refused. On MySQL REPEATABLE READ only the locked
    re-read is current; without the fix the PATCH lands (200) and the DELETE
    removes the new superuser (204)."""
    from sqlalchemy import update  # noqa: PLC0415

    from faststudio.api import write as write_module  # noqa: PLC0415

    if method == "delete":  # otherwise the permission check refuses before the race
        async with AsyncSession(db) as session:
            permission = AuthPermission(codename="users.delete")
            session.add(permission)
            await session.flush()
            await session.execute(
                insert(user_permissions),
                [{"user_id": MANAGER, "permission_id": permission.id}],
            )
            await session.commit()
    manager = await sign_in("manager")
    original = vars(write_module)["check_escalation"]
    promoted: list[bool] = []

    async def promote_meanwhile(*args: object, **kwargs: object) -> None:
        try:
            async with db.begin() as conn:  # root's concurrent promotion commits
                await conn.execute(
                    update(AuthUser).where(AuthUser.id == ALICE).values(is_superuser=True)
                )
        finally:
            promoted.append(True)  # the race really happened (or was attempted)
        await original(*args, **kwargs)

    monkeypatch.setattr(write_module, "check_escalation", promote_meanwhile)
    path = f"/models/users/items/{ALICE}"
    response = await (manager.delete(path) if method == "delete" else manager.patch(path, body))
    assert promoted == [True]
    # SQLite serializes writers: during the delete the request already holds the
    # write lock, so the promotion itself fails and the request is a 409.
    expected = 409 if (db.dialect.name, method) == ("sqlite", "delete") else 403
    assert response.status_code == expected, response.text
    async with AsyncSession(db) as session:
        alice = await session.get(AuthUser, ALICE)
        assert alice is not None  # never deleted
        assert (alice.username, alice.is_active) == ("alice", True)  # never changed


async def test_a_grant_takes_effect_on_the_next_request(sign_in: SignIn, db: AsyncEngine) -> None:
    manager = await sign_in("manager")
    response = await manager.patch(f"/models/users/items/{ALICE}", {"groups": [READERS]})
    assert response.status_code == 200, response.text
    assert await _group_ids(db, ALICE) == [READERS]
    assert await _codenames_of(db, ALICE) == {"docs.view"}


async def test_concurrent_membership_writes_never_fail_with_500(sign_in: SignIn) -> None:
    first, second = await sign_in("manager"), await sign_in("manager")
    results = await asyncio.gather(
        first.patch(f"/models/groups/items/{READERS}", {"users": [ALICE]}),
        second.patch(f"/models/users/items/{ALICE}", {"groups": [READERS]}),
    )
    assert all(r.status_code in {200, 409} for r in results), [r.text for r in results]
    assert any(r.status_code == 200 for r in results)
