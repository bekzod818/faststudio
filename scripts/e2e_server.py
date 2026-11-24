"""Minimal FastStudio server for Playwright E2E runs (replaced by examples/basic in M12).

Serves the built SPA from src/faststudio/static through the real admin
mount, so E2E tests exercise the production CSP and security headers.
A temporary SQLite database is seeded with one administrator whose
credentials come from FASTSTUDIO_E2E_USERNAME / FASTSTUDIO_E2E_PASSWORD
(test-only defaults; this server never runs outside the E2E suite).

Usage: python scripts/e2e_server.py [port]
"""

from __future__ import annotations

import enum
import os
import secrets
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import uvicorn
from fastapi import FastAPI
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from faststudio import Admin, ModelAdmin, ModelUserBackend, hash_password

E2E_USERNAME = os.environ.get("FASTSTUDIO_E2E_USERNAME", "e2e-admin")
E2E_PASSWORD = os.environ.get("FASTSTUDIO_E2E_PASSWORD", "e2e-only-password")


class _Base(DeclarativeBase):
    pass


class E2EUser(_Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Category(_Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # Deleting a category that still has products is refused (409).
    products: Mapped[list[Product]] = relationship(back_populates="category")


class Status(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Product(_Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[Status | None] = mapped_column(Enum(Status), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category: Mapped[Category | None] = relationship(back_populates="products")


class Task(_Base):
    """Written to by the form E2E tests; products stay read-only for list tests."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80), comment="What needs doing.")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimate: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[Status | None] = mapped_column(Enum(Status), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


PRODUCT_COUNT = 30  # three pages of ten


class CategoryAdmin(ModelAdmin, model=Category):
    list_display = ("id", "name")
    search_fields = ("name",)


class ProductAdmin(ModelAdmin, model=Product):
    list_display = ("id", "name", "price", "in_stock", "status", "category_id", "created_at")
    search_fields = ("name",)
    list_filter = ("in_stock", "status")
    ordering = ("id",)
    page_size = 10


def _seed_rows() -> list[_Base]:
    hardware, books = Category(id=1, name="Hardware"), Category(id=2, name="Books")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    statuses = [Status.DRAFT, Status.PUBLISHED, Status.ARCHIVED, None]
    products: list[_Base] = [
        Product(
            id=i,
            name=f"{'Widget' if i % 2 else 'Gadget'} {i:02d}",
            price=Decimal(i * 5) + Decimal("0.99"),
            in_stock=i % 3 != 0,
            status=statuses[i % 4],
            category_id=1 if i % 2 else 2,
            created_at=start + timedelta(days=i),
        )
        for i in range(1, PRODUCT_COUNT + 1)
    ]
    return [hardware, books, *products]


class TaskAdmin(ModelAdmin, model=Task):
    list_display = ("id", "title", "done", "priority", "category_id")
    search_fields = ("title",)
    readonly_fields = ("created_at",)


class UserAdmin(ModelAdmin, model=E2EUser):
    list_display = ("id", "username", "is_active", "is_admin")
    exclude = ("password_hash",)
    can_create = False  # the password hash cannot be set from the admin yet


def build_app() -> FastAPI:
    """Create the E2E application with a throwaway secret and a seeded database."""
    # A throwaway file, not a shared in-memory connection: parallel E2E tests
    # write concurrently and need independent transactions.
    workdir = tempfile.TemporaryDirectory(prefix="faststudio-e2e-")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{workdir.name}/e2e.db", connect_args={"timeout": 30}
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                E2EUser(
                    username=E2E_USERNAME,
                    password_hash=hash_password(E2E_PASSWORD),
                    is_active=True,
                    is_admin=True,
                )
            )
            session.add_all(_seed_rows())
        yield
        await engine.dispose()
        workdir.cleanup()

    app = FastAPI(lifespan=lifespan)
    admin = Admin(
        app,
        engine=engine,
        auth_backend=ModelUserBackend(E2EUser),
        secret_key=secrets.token_urlsafe(48),
        secure_cookies=False,  # plain-HTTP 127.0.0.1 test server
    )
    admin.register(UserAdmin)
    admin.register(CategoryAdmin)
    admin.register(ProductAdmin)
    admin.register(TaskAdmin)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4173
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
