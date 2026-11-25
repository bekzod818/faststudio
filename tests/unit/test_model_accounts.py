"""ModelUserBackend.create_admin rules (M19)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Date, String
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from faststudio import ModelUserBackend


class _Base(DeclarativeBase):
    pass


class Person(_Base):
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=False)
    is_admin: Mapped[bool] = mapped_column(default=False)
    email: Mapped[str] = mapped_column(String(100))
    born: Mapped[date] = mapped_column(Date)  # required, not text


class Simple(_Base):
    __tablename__ = "simple_people"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=False)
    is_admin: Mapped[bool] = mapped_column(default=False)
    email: Mapped[str] = mapped_column(String(100))


async def test_required_columns_that_are_not_text(engine: AsyncEngine) -> None:
    accounts: Any = ModelUserBackend(Person).faststudio_capabilities.accounts
    assert set(accounts.required_fields()) == {"email", "born"}
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="born are not text"):
            await accounts.create_admin(
                session, username="u", password="p" * 12, fields={"email": "x"}
            )


async def test_missing_required_values(engine: AsyncEngine) -> None:
    accounts: Any = ModelUserBackend(Simple).faststudio_capabilities.accounts
    async with AsyncSession(engine) as session:
        with pytest.raises(ValueError, match="Missing required value"):
            await accounts.create_admin(session, username="u", password="p" * 12, fields={})
