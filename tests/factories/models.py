"""SQLAlchemy models used across the test suite."""

from __future__ import annotations

import enum
import json
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Double,
    Enum,
    FetchedValue,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    PickleType,
    Sequence,
    SmallInteger,
    String,
    Text,
    Time,
    TypeDecorator,
    Unicode,
    UnicodeText,
    Uuid,
    func,
)
from sqlalchemy.dialects import postgresql
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


# --- every column type the introspection layer must classify
class Letter(enum.Enum):
    A_ONE = 1
    IN_PROGRESS = 2


class AllTypes(Base):
    __tablename__ = "all_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    s_len: Mapped[str] = mapped_column(String(50), comment="A short string")
    s_unicode: Mapped[str] = mapped_column(Unicode(20))
    s_nolen: Mapped[str | None] = mapped_column(String())
    t_text: Mapped[str | None] = mapped_column(Text)
    t_unicode: Mapped[str | None] = mapped_column(UnicodeText)
    i_int: Mapped[int] = mapped_column(Integer, default=7)
    i_small: Mapped[int | None] = mapped_column(SmallInteger)
    i_big: Mapped[int | None] = mapped_column(BigInteger)
    f_float: Mapped[float | None] = mapped_column(Float)
    f_double: Mapped[float | None] = mapped_column(Double)
    d_numeric: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1.50"))
    d_numeric_float: Mapped[float | None] = mapped_column(Numeric(8, 3, asdecimal=False))
    b_bool: Mapped[bool] = mapped_column(Boolean, server_default="1")
    dt_date: Mapped[date | None] = mapped_column(Date, default=date(2026, 1, 2))
    dt_naive: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    dt_aware: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    e_enum: Mapped[Role] = mapped_column(Enum(Role), default=Role.EDITOR)
    e_letters: Mapped[Letter | None] = mapped_column(Enum(Letter))
    e_strings: Mapped[str | None] = mapped_column(Enum("draft", "published", name="status"))
    j_json: Mapped[Any] = mapped_column(JSON, default=dict)
    j_jsonb: Mapped[Any | None] = mapped_column(postgresql.JSONB)
    u_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    u_pg_uuid: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    x_time: Mapped[time | None] = mapped_column(Time)
    x_interval: Mapped[timedelta | None] = mapped_column(Interval)
    x_binary: Mapped[bytes | None] = mapped_column(LargeBinary)
    x_pickle: Mapped[Any | None] = mapped_column(PickleType)
    x_array: Mapped[list[int] | None] = mapped_column(postgresql.ARRAY(Integer))
    x_variant: Mapped[str | None] = mapped_column(String(10).with_variant(Text(), "postgresql"))
    fk_team: Mapped[int | None] = mapped_column("team_id", ForeignKey("teams.id"))
    g_computed: Mapped[int | None] = mapped_column(Integer, Computed("i_int * 2"))
    wrapped: Mapped[str | None] = mapped_column(LowerString)


class Country(Base):
    """Natural primary key: required and writable on create."""

    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Ticket(Base):
    """Identity and UUID primary keys, composite FK, self-reference."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[int] = mapped_column(Integer, Identity())
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"))
    country_code: Mapped[str | None] = mapped_column(ForeignKey("countries.code"))
    member_user: Mapped[int | None] = mapped_column(Integer)
    member_team: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        ForeignKeyConstraint(
            ["member_user", "member_team"], ["memberships.user_id", "memberships.team_id"]
        ),
    )


# --- columns managed by the mapper, the app or the database
class Versioned(Base):
    __tablename__ = "versioned"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(50))
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class JSONEncodedDict(TypeDecorator[Any]):
    """SQLAlchemy docs recipe: stores JSON text in VARCHAR; Python type is dict."""

    impl = String(200)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else json.dumps(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else json.loads(value)


class KeyHolder(Base):
    __tablename__ = "keyholders"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)


class Audited(Base):
    __tablename__ = "audited"

    id: Mapped[int] = mapped_column(primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    touched_at: Mapped[datetime | None] = mapped_column(DateTime, server_onupdate=FetchedValue())
    trigger_set: Mapped[str] = mapped_column(String(10), server_default=FetchedValue())
    seq_no: Mapped[int] = mapped_column(Integer, Sequence("audited_seq"))
    api_token: Mapped[str] = mapped_column(String(50), default="sk_live_example")
    blob: Mapped[Any] = mapped_column(PickleType, default={"k": "v"})
    payload: Mapped[Any | None] = mapped_column(JSONEncodedDict)
    plain_note: Mapped[str] = mapped_column(String(20), default="hello")
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=1.5)
    variant_fk: Mapped[str | None] = mapped_column(
        String(2).with_variant(Text(), "postgresql"), ForeignKey("countries.code")
    )
    dialect_fk: Mapped[str | None] = mapped_column(DialectString, ForeignKey("countries.code"))
    key_ref: Mapped[str | None] = mapped_column(String(64), ForeignKey("keyholders.api_key_hash"))
    small: Mapped[int | None] = mapped_column(SmallInteger)
    big: Mapped[int | None] = mapped_column(BigInteger)


class Orphan(Base):
    """FK to a table that is not in the metadata."""

    __tablename__ = "orphans"

    id: Mapped[int] = mapped_column(primary_key=True)
    ghost_id: Mapped[int | None] = mapped_column(ForeignKey("ghosts.id"))


class Clock(Base):
    """A NOT NULL column of an unsupported type: creates can never supply it."""

    __tablename__ = "clocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[time] = mapped_column(Time, nullable=False)


# --- custom types that convert values through other hooks: must be unsupported
class BindProc(TypeDecorator[Any]):
    impl = String(50)
    cache_ok = True

    def bind_processor(self, dialect: Dialect) -> Any:
        return json.dumps


class ResultProc(TypeDecorator[Any]):
    impl = String(50)
    cache_ok = True

    def result_processor(self, dialect: Dialect, coltype: object) -> Any:
        return json.loads


class BindExpr(TypeDecorator[str]):
    """pgcrypto-style: encrypts in SQL."""

    impl = String(50)
    cache_ok = True

    def bind_expression(self, bindvalue: Any) -> Any:
        return func.pgp_sym_encrypt(bindvalue, "k")


class ColExpr(TypeDecorator[str]):
    impl = String(50)
    cache_ok = True

    def column_expression(self, column: Any) -> Any:
        return func.pgp_sym_decrypt(column, "k")


class StringSub(String):
    """A direct subclass of a supported base type that converts values."""

    def bind_processor(self, dialect: Dialect) -> Any:
        return json.dumps


class PlainStringSub(String):
    """A direct subclass that changes nothing: still a string."""


class Hooked(Base):
    __tablename__ = "hooked"

    id: Mapped[int] = mapped_column(primary_key=True)
    bind_proc: Mapped[Any] = mapped_column(BindProc)
    result_proc: Mapped[Any] = mapped_column(ResultProc)
    bind_expr: Mapped[str | None] = mapped_column(BindExpr)
    col_expr: Mapped[str | None] = mapped_column(ColExpr)
    string_sub: Mapped[Any] = mapped_column(StringSub(30))
    plain_sub: Mapped[str | None] = mapped_column(PlainStringSub(30))
    ratio: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), default=Decimal("1.5"))
