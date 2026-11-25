"""SQLAlchemy 2.0 models for the example: one of each field type FastStudio maps."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Accounts. Rows with ``is_active`` and ``is_admin`` can sign in to the admin."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deleting a category that still has products is refused (409).
    products: Mapped[list[Product]] = relationship(back_populates="category")


class Status(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    sku: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[Status | None] = mapped_column(Enum(Status), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment='Free-form JSON, e.g. {"color": "red"}.'
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category: Mapped[Category | None] = relationship(back_populates="products")


class Tag(Base):
    """Labels for tasks (the many-to-many example)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)


# A plain association table: two foreign keys, their pair as the primary key.
task_tags = Table(
    "task_tags",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Task(Base):
    """Back-office to-dos."""

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    tags: Mapped[list[Tag]] = relationship(secondary=task_tags)
