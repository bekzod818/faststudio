"""The example application.

    export FASTSTUDIO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    python -m examples.basic   # first start creates the tables; Ctrl-C
    faststudio createadmin --app examples.basic.app:create_app --username admin
    python -m examples.basic   # or: uvicorn examples.basic.app:create_app --factory

The database defaults to ``./example.db`` (``FASTSTUDIO_EXAMPLE_DATABASE_URL``
overrides it) and is filled with demo data on first start.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import ClassVar

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from examples.basic.db import create_or_update_admin, create_tables, seed_demo_data
from examples.basic.models import Category, Product, Tag, Task, User
from faststudio import Admin, ModelAdmin, ModelUserBackend

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./example.db"


class UserAdmin(ModelAdmin, model=User):
    list_display = ("id", "username", "email", "is_active", "is_admin")
    search_fields = ("username", "email")
    list_filter = ("is_active", "is_admin")
    # Never show or accept password hashes. Accounts (and passwords) are
    # created with `faststudio createadmin --app examples.basic.app:create_app`.
    exclude = ("password_hash",)
    readonly_fields = ("created_at",)
    can_create = False


class CategoryAdmin(ModelAdmin, model=Category):
    list_display = ("id", "name")
    search_fields = ("name",)


class ProductAdmin(ModelAdmin, model=Product):
    list_display = ("id", "name", "price", "in_stock", "status", "category_id", "created_at")
    search_fields = ("name",)
    list_filter = ("in_stock", "status")
    ordering = ("id",)
    page_size = 10
    column_labels: ClassVar[dict[str, str]] = {"sku": "SKU"}


class TaskAdmin(ModelAdmin, model=Task):
    list_display = ("id", "title", "done", "priority", "category_id")
    search_fields = ("title",)
    list_filter = ("done", "status")
    readonly_fields = ("created_at",)
    # Edited as a searchable multi-select; at most 20 tags per task.
    many_to_many = ("tags",)
    many_to_many_limits: ClassVar[dict[str, int]] = {"tags": 20}


class TagAdmin(ModelAdmin, model=Tag):
    list_display = ("id", "name")
    search_fields = ("name",)


def create_app(
    database_url: str | None = None,
    *,
    bootstrap_admin: tuple[str, str] | None = None,
) -> FastAPI:
    """Build the example app.

    ``bootstrap_admin`` (username, password) creates or resets that admin at
    startup; it exists for throwaway demo/test databases (see ``__main__``).
    """
    engine = create_async_engine(
        database_url or os.environ.get("FASTSTUDIO_EXAMPLE_DATABASE_URL", DEFAULT_DATABASE_URL),
        # Keep bound values (e.g. password hashes) out of error messages and logs.
        hide_parameters=True,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await create_tables(engine)
            await seed_demo_data(session_maker)
            if bootstrap_admin is not None:
                await create_or_update_admin(session_maker, *bootstrap_admin)
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="FastStudio example", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    async def home() -> RedirectResponse:
        return RedirectResponse("/admin/")

    # secret_key comes from FASTSTUDIO_SECRET_KEY; startup fails without one.
    admin = Admin(
        app,
        session_maker=session_maker,
        auth_backend=ModelUserBackend(User),
    )
    for model_admin in (UserAdmin, CategoryAdmin, ProductAdmin, TaskAdmin, TagAdmin):
        admin.register(model_admin)
    return app
