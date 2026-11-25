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
    Column,
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
    Index,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    PickleType,
    Sequence,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    TypeDecorator,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    Uuid,
    and_,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship
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


# --- single-table inheritance: the subclass shares employees.id with its base
class Manager(Employee):
    __mapper_args__ = {"polymorphic_identity": "manager"}  # noqa: RUF012


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))


# --- admin accounts for authentication tests
class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Operator(Base):
    """Custom column names and a UUID primary key."""

    __tablename__ = "operators"

    uid: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(150), unique=True)
    secret: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CompositeLogin(Base):
    __tablename__ = "composite_logins"

    tenant: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(50))
    pw: Mapped[str] = mapped_column(String(255))


class DatedLogin(Base):
    __tablename__ = "dated_logins"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    login: Mapped[str] = mapped_column(String(50))
    pw: Mapped[str] = mapped_column(String(255))


class LegacyAdmin(Base):
    """Username not declared unique; nullable password (e.g. SSO-only accounts)."""

    __tablename__ = "legacy_admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class IndexedAdmin(Base):
    """Uniqueness declared through a unique index."""

    __tablename__ = "indexed_admins"
    __table_args__ = (Index("ix_indexed_admins_username", "username", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class TenantAdmin(Base):
    """Usernames unique only per tenant: not unique on their own."""

    __tablename__ = "tenant_admins"
    __table_args__ = (UniqueConstraint("tenant", "username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Gauge(Base):
    """Portable value-encoding fixture (creatable on SQLite)."""

    __tablename__ = "gauges"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50))
    big: Mapped[int | None] = mapped_column(BigInteger)
    ratio: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    role: Mapped[Role | None] = mapped_column(Enum(Role))
    token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    doc: Mapped[Any | None] = mapped_column(JSON)
    day: Mapped[date | None] = mapped_column(Date)
    stamp: Mapped[datetime | None] = mapped_column(DateTime)
    flag: Mapped[bool | None] = mapped_column(Boolean)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))


class Mentorship(Base):
    """FK to a joined-inheritance subclass (engineers.id)."""

    __tablename__ = "mentorships"

    id: Mapped[int] = mapped_column(primary_key=True)
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("engineers.id"))


class Note(Base):
    """Write-API fixture: required, optional, readonly, excluded and FK fields."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(20))
    body: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    status: Mapped[Role | None] = mapped_column(Enum(Role))
    due: Mapped[datetime | None] = mapped_column(DateTime)
    stamped: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    secret: Mapped[str] = mapped_column(String(50), default="s3cret-default")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))


# --- ORM relationships: deletes must not run cascades behind the admin's back
class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    children: Mapped[list[Child]] = relationship(back_populates="parent")


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("parents.id"))
    parent: Mapped[Parent | None] = relationship(back_populates="children")


class Doc(Base):
    """A readonly column reachable through a second attribute."""

    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)


setattr(Doc, "created_alias", column_property(Doc.__table__.c.created_at))  # noqa: B010


class Awkward(Base):
    """Attribute names that collide with pydantic internals."""

    __tablename__ = "awkward"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_config: Mapped[str | None] = mapped_column("cfg", String(20))
    json: Mapped[str | None] = mapped_column("js", String(20))
    _hidden: Mapped[str | None] = mapped_column("hidden", String(20))


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Pet(Base):
    """Many-to-one with a delete cascade: deleting a pet would delete its owner."""

    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"))
    owner: Mapped[Owner | None] = relationship(cascade="all")


post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", ForeignKey("posts.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50))


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    tags: Mapped[list[Tag]] = relationship(secondary=post_tags)


# --------------------------------------------------------------------------- many-to-many


follows = Table(
    "follows",
    Base.metadata,
    Column("follower_id", ForeignKey("people.id"), primary_key=True),
    Column("followed_id", ForeignKey("people.id"), primary_key=True),
)


class Person(Base):
    """Self-referential many-to-many."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    follows: Mapped[list[Person]] = relationship(
        secondary=follows,
        primaryjoin=lambda: Person.id == follows.c.follower_id,
        secondaryjoin=lambda: Person.id == follows.c.followed_id,
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


#: Plain: a primary key over both FKs plus an extra column with a server default.
article_topics = Table(
    "article_topics",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id"), primary_key=True),
    Column("linked_at", DateTime, server_default=func.now()),
)
#: Plain but without a primary key or unique constraint (registration warns).
article_loose_topics = Table(
    "article_loose_topics",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id"), nullable=False),
    Column("topic_id", ForeignKey("topics.id"), nullable=False),
)
#: Not plain: an extra column without a default.
article_weighted_topics = Table(
    "article_weighted_topics",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id"), primary_key=True),
    Column("weight", Integer, nullable=False),
)


class Article(Base):
    """Many-to-many relationships covering every plain / non-plain case."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    topics: Mapped[list[Topic]] = relationship(secondary=article_topics)
    loose_topics: Mapped[list[Topic]] = relationship(secondary=article_loose_topics)
    weighted_topics: Mapped[list[Topic]] = relationship(secondary=article_weighted_topics)
    #: Not plain: the secondaryjoin filters on a target column.
    active_topics: Mapped[list[Topic]] = relationship(
        secondary=article_topics,
        secondaryjoin=lambda: and_(Topic.id == article_topics.c.topic_id, Topic.active.is_(True)),
        viewonly=True,
    )
    filtered_topics: Mapped[list[Topic]] = relationship(
        secondary=article_topics,
        secondaryjoin=lambda: and_(Topic.id == article_topics.c.topic_id, Topic.active.is_(True)),
        overlaps="topics",
    )
    #: Plain, but view-only: shown read-only.
    seen_topics: Mapped[list[Topic]] = relationship(secondary=article_topics, viewonly=True)


class Label(Base):
    """String primary key: a many-to-many target."""

    __tablename__ = "labels"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Token(Base):
    """UUID primary key: a many-to-many target."""

    __tablename__ = "tokens"

    uid: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


board_labels = Table(
    "board_labels",
    Base.metadata,
    Column("board_id", ForeignKey("boards.id"), primary_key=True),
    Column("label_code", ForeignKey("labels.code"), primary_key=True),
)
board_tokens = Table(
    "board_tokens",
    Base.metadata,
    Column("board_id", ForeignKey("boards.id"), primary_key=True),
    Column("token_uid", ForeignKey("tokens.uid"), primary_key=True),
)


class Board(Base):
    """Many-to-many to string- and UUID-keyed targets."""

    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    labels: Mapped[list[Label]] = relationship(secondary=board_labels)
    tokens: Mapped[list[Token]] = relationship(secondary=board_tokens)


class Twin(Base):
    """Two writable attributes on one column: conflicting values in one body."""

    __tablename__ = "twins"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(20))


setattr(Twin, "label_alias", column_property(Twin.__table__.c.label))  # noqa: B010
