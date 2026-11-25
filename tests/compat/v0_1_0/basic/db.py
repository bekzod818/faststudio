"""Database setup, demo data and admin accounts for the example."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.compat.v0_1_0.basic.models import Base, Category, Product, Status, Task, User
from faststudio import hash_password

PRODUCT_COUNT = 30
MIN_PASSWORD_LENGTH = 12
MAX_USERNAME_LENGTH = 150  # FastStudio's login accepts at most 150 characters


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _demo_rows() -> list[Base]:
    """Deterministic demo data (the Playwright suite relies on it)."""
    hardware = Category(id=1, name="Hardware", description="Tools and parts.")
    books = Category(id=2, name="Books")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    statuses = [Status.DRAFT, Status.PUBLISHED, Status.ARCHIVED, None]
    products: list[Base] = [
        Product(
            id=i,
            name=f"{'Widget' if i % 2 else 'Gadget'} {i:02d}",
            sku=uuid.UUID(int=i),
            price=Decimal(i * 5) + Decimal("0.99"),
            in_stock=i % 3 != 0,
            status=statuses[i % 4],
            category_id=1 if i % 2 else 2,
            attributes={"color": "red" if i % 2 else "blue", "weight_g": i * 10},
            created_at=start + timedelta(days=i),
        )
        for i in range(1, PRODUCT_COUNT + 1)
    ]
    tasks: list[Base] = [
        Task(title="Restock widgets", priority=1, status=Status.PUBLISHED, category_id=1),
        Task(title="Review book prices", priority=2, estimate=Decimal("1.50")),
    ]
    return [hardware, books, *products, *tasks]


async def seed_demo_data(session_maker: async_sessionmaker[AsyncSession]) -> bool:
    """Insert demo rows into an empty database. Returns whether it seeded."""
    async with session_maker() as session, session.begin():
        for model in (Category, Product):
            if await session.scalar(select(func.count()).select_from(model)):
                return False
        session.add_all(_demo_rows())
    return True


def _check_username(username: str) -> None:
    """Accept only usernames FastStudio's login can match."""
    if not username or username != username.strip():
        msg = "The username must not be empty or start/end with spaces."
        raise ValueError(msg)
    if len(username) > MAX_USERNAME_LENGTH:
        msg = f"Use a username of at most {MAX_USERNAME_LENGTH} characters."
        raise ValueError(msg)
    # Control and invisible formatting characters (e.g. bidi overrides).
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in username):
        msg = "The username contains invalid characters."
        raise ValueError(msg)


async def create_or_update_admin(
    session_maker: async_sessionmaker[AsyncSession], username: str, password: str
) -> bool:
    """Create an admin account, or reset its password. Returns True if created."""
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."
        raise ValueError(msg)
    _check_username(username)
    async with session_maker() as session, session.begin():
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    is_active=True,
                    is_admin=True,
                )
            )
            return True
        user.password_hash = hash_password(password)
        user.is_active = True
        user.is_admin = True
        return False
