"""SQLAlchemy models used across the test suite."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    func,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column
from sqlalchemy.types import TypeEngine


class Base(DeclarativeBase):
    pass


class Role(enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class LowerString(TypeDecorator[str]):
    """A TypeDecorator over String: must be treated as a string column."""

    impl = String(100)
    cache_ok = True


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


# A SQL-expression attribute: readable, but not an editable column field.
setattr(Team, "name_upper", column_property(func.upper(Team.__table__.c.name)))  # noqa: B010


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column("name", String(100))  # attribute key != column name
    bio: Mapped[str | None] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(LowerString)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.VIEWER)
    password_hash: Mapped[str] = mapped_column(String(255))
    login_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(50))


class Membership(Base):
    """Composite primary key: unsupported in v0.1."""

    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)


class NotMapped:
    """A plain class that SQLAlchemy does not map."""


# --- joined-table inheritance: the subclass pk maps to two columns
class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    __mapper_args__ = {"polymorphic_on": "kind", "polymorphic_identity": "employee"}  # noqa: RUF012


class Engineer(Employee):
    __tablename__ = "engineers"

    id: Mapped[int] = mapped_column(ForeignKey("employees.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String(50))
    __mapper_args__ = {"polymorphic_identity": "engineer"}  # noqa: RUF012


# --- one column exposed through two attributes, plus a foreign-table column
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(50))
    secret_hash: Mapped[str] = mapped_column(String(255))


setattr(Account, "hash_alias", column_property(Account.__table__.c.secret_hash))  # noqa: B010
setattr(Account, "team_name", column_property(Team.__table__.c.name))  # noqa: B010


# --- type wrappers
class Flag(TypeDecorator[bool]):
    impl = Boolean
    cache_ok = True


class RoleType(TypeDecorator[Role]):
    impl = Enum(Role)
    cache_ok = True


class DialectString(TypeDecorator[str]):
    """Implementation depends on the dialect: cannot be classified statically."""

    impl = String(50)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(Integer() if dialect.name == "sqlite" else String(50))


class Gadget(Base):
    __tablename__ = "gadgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    flag: Mapped[bool] = mapped_column(Flag)
    kind: Mapped[Role] = mapped_column(RoleType)
    variant_label: Mapped[str] = mapped_column(String(50).with_variant(Integer(), "sqlite"))
    dialect_label: Mapped[str] = mapped_column(DialectString)


# --- aliases written the usual ways: annotated copies of the same table column
class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50))
    secret_hash: Mapped[str] = mapped_column(String(255))


setattr(Vault, "alias_attr", column_property(Vault.secret_hash))  # noqa: B010
setattr(Vault, "alias_expr", column_property(Vault.secret_hash.expression))  # noqa: B010
