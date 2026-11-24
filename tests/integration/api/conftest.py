"""A seeded database and a signed-in client for API tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from faststudio import Admin, ModelAdmin, ModelUserBackend, hash_password
from tests.factories.models import (
    AdminUser,
    Assignment,
    Base,
    Child,
    Country,
    Employee,
    Engineer,
    Gauge,
    Manager,
    Mentorship,
    Note,
    Owner,
    Parent,
    Pet,
    Post,
    Role,
    Tag,
    Team,
    User,
)

TABLES = (
    "admin_users",
    "teams",
    "users",
    "gauges",
    "employees",
    "engineers",
    "assignments",
    "mentorships",
    "notes",
    "countries",
    "parents",
    "children",
    "owners",
    "pets",
    "tags",
    "posts",
    "post_tags",
)
USER_COUNT = 30


@pytest.fixture
async def db() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[Base.metadata.tables[t] for t in TABLES]
        )
    async with async_sessionmaker(engine)() as session:
        session.add(
            AdminUser(username="admin", password_hash=hash_password("pw-admin"), is_admin=True)
        )
        session.add_all(
            [Team(id=1, name="Core"), Team(id=2, name="Growth"), Team(id=3, name="Ops")]
        )
        await session.flush()  # referenced rows first (foreign keys are enforced)
        roles = [Role.ADMIN, Role.EDITOR, Role.VIEWER]
        for i in range(1, USER_COUNT + 1):
            session.add(
                User(
                    id=i,
                    email=f"user{i:02d}@example.com",
                    full_name=f"User {i:02d}",
                    bio="likes 100% coverage" if i == 7 else None,
                    handle="under_score" if i == 8 else None,
                    is_active=i % 3 != 0,
                    role=roles[i % 3],
                    password_hash=f"SECRET-HASH-{i}",
                    login_count=i,
                    created_at=datetime(2026, 1, i % 28 + 1, 12, 0, 0),
                    team_id=(i % 3) + 1 if i != 30 else None,
                )
            )
        session.add(
            Gauge(
                id=1,
                label="g",
                big=2**60,
                ratio=float("nan"),
                amount=Decimal("12.50"),
                role=Role.ADMIN,
                token=uuid.UUID(int=5),
                blob=b"\x00\x01\x02",
                doc={"k": [1, 2], "n": 2**60},
                day=date(2026, 1, 2),
                stamp=datetime(2026, 1, 2, 3, 4, 5),
                flag=True,
                team_id=1,
            )
        )
        await session.flush()
        session.add_all([Employee(id=1), Engineer(id=2, language="python"), Manager(id=3)])
        await session.flush()
        session.add_all(
            [
                Assignment(id=1, employee_id=2),
                Assignment(id=2, employee_id=3),
                Mentorship(id=1, engineer_id=2),
                Note(id=1, title="first", secret="NOTE-SECRET", team_id=1),
                Country(code="UZ", name="Uzbekistan"),
                Parent(id=1, name="with child"),
                Parent(id=2, name="childless"),
            ]
        )
        session.add_all([Owner(id=1, name="alice"), Tag(id=1, label="news")])
        await session.flush()
        session.add(Child(id=1, parent_id=1))
        session.add_all([Pet(id=1, owner_id=1), Pet(id=2, owner_id=None)])
        tag = await session.get(Tag, 1)
        session.add_all(
            [Post(id=1, title="tagged", tags=[tag]), Post(id=2, title="plain", tags=[])]
        )
        await session.commit()
    yield engine
    await engine.dispose()


class TeamAdmin(ModelAdmin, model=Team):
    list_display = ("id", "name")
    search_fields = ("name",)


class UserAdmin(ModelAdmin, model=User):
    list_display = ("id", "email", "is_active", "role", "team_id")
    search_fields = ("email", "full_name", "bio", "handle")
    list_filter = ("is_active", "role")
    ordering = ("id",)
    exclude = ("password_hash",)
    page_size = 10


class GaugeAdmin(ModelAdmin, model=Gauge):
    list_display = ("id", "big", "ratio", "amount", "role")
    list_filter = ("role", "flag")


class EngineerAdmin(ModelAdmin, model=Engineer):
    """Joined-table subclass; its label field (`kind`) lives on the base table."""

    list_display = ("id", "kind", "language")


class ManagerAdmin(ModelAdmin, model=Manager):
    """Single-table subclass registered without its base model."""

    identity = "managers"
    list_display = ("id", "kind")
    can_create = False
    can_edit = False


class NoteAdmin(ModelAdmin, model=Note):
    list_display = ("id", "title", "priority", "team_id")
    exclude = ("secret",)
    readonly_fields = ("created_at",)


class CountryAdmin(ModelAdmin, model=Country):
    list_display = ("code", "name")
    can_delete = False


class ParentAdmin(ModelAdmin, model=Parent):
    list_display = ("id", "name")


class ChildAdmin(ModelAdmin, model=Child):
    list_display = ("id", "parent_id")


class PetAdmin(ModelAdmin, model=Pet):
    list_display = ("id", "owner_id")


class PostAdmin(ModelAdmin, model=Post):
    list_display = ("id", "title")


class AssignmentAdmin(ModelAdmin, model=Assignment):
    list_display = ("id", "employee_id")


class MentorshipAdmin(ModelAdmin, model=Mentorship):
    list_display = ("id", "engineer_id")


@pytest.fixture
def admin_options() -> dict[str, Any]:
    """Extra `Admin(...)` options; tests override it with `parametrize`."""
    return {}


@pytest.fixture
def admin(  # noqa: PLR0917 - pytest fixtures
    app: FastAPI,
    db: AsyncEngine,
    secret_key: str,
    static_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    admin_options: dict[str, Any],
) -> Admin:
    monkeypatch.setattr("faststudio.admin._STATIC_DIR", static_dir)
    instance = Admin(
        app,
        engine=db,
        auth_backend=ModelUserBackend(AdminUser),
        secret_key=secret_key,
        **admin_options,
    )
    instance.register(TeamAdmin)
    instance.register(UserAdmin)
    for admin_class in (
        GaugeAdmin,
        EngineerAdmin,
        ManagerAdmin,
        AssignmentAdmin,
        MentorshipAdmin,
        NoteAdmin,
        CountryAdmin,
        ParentAdmin,
        ChildAdmin,
        PetAdmin,
        PostAdmin,
    ):
        instance.register(admin_class)
    return instance


@pytest.fixture
async def api(admin: Admin, app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTPS client signed in as an admin."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        await client.get("/admin/")
        token = client.cookies.get("faststudio_csrftoken")
        assert token
        response = await client.post(
            "/admin/api/v1/auth/login",
            json={"username": "admin", "password": "pw-admin"},
            headers={"x-faststudio-csrf": token},
        )
        assert response.status_code == 200
        yield client
