"""Plain many-to-many detection (ADR-0010 §1)."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    configure_mappers,
    mapped_column,
    relationship,
)

from faststudio.introspection._many import NotPlainError, plain_many_to_many
from tests.factories.models import (
    Article,
    Parent,
    Person,
    Pet,
    Post,
    Tag,
    Topic,
    article_loose_topics,
    article_topics,
    follows,
    post_tags,
)


def _rel(model: type[Any], name: str) -> Any:
    return sa_inspect(model).relationships[name]


def test_plain_secondary() -> None:
    link = plain_many_to_many(_rel(Post, "tags"))
    assert link.secondary is post_tags
    assert (link.local_fk.name, link.remote_fk.name) == ("post_id", "tag_id")
    assert link.local_pk is Post.__table__.c.id
    assert link.target_pk is Tag.__table__.c.id
    assert link.target_model is Tag
    assert link.value_type == "integer"
    assert link.unique_pair is True
    assert link.viewonly is False


def test_self_referential() -> None:
    link = plain_many_to_many(_rel(Person, "follows"))
    assert link.secondary is follows
    assert (link.local_fk.name, link.remote_fk.name) == ("follower_id", "followed_id")
    assert link.local_pk is link.target_pk is Person.__table__.c.id


def test_extra_column_with_a_default_is_still_plain() -> None:
    assert plain_many_to_many(_rel(Article, "topics")).secondary is article_topics


def test_secondary_without_unique_pair_is_plain_but_flagged() -> None:
    link = plain_many_to_many(_rel(Article, "loose_topics"))
    assert link.secondary is article_loose_topics
    assert link.unique_pair is False


def test_viewonly_plain_relationship() -> None:
    link = plain_many_to_many(_rel(Article, "seen_topics"))
    assert link.viewonly is True
    assert link.target_model is Topic


@pytest.mark.parametrize(
    ("model", "name", "reason"),
    [
        (Article, "weighted_topics", "column 'weight' has no default"),
        (Article, "active_topics", "custom join condition"),
        (Article, "filtered_topics", "custom join condition"),
        (Parent, "children", "not a many-to-many relationship"),
        (Pet, "owner", "not a many-to-many relationship"),
    ],
)
def test_not_plain(model: type[Any], name: str, reason: str) -> None:
    with pytest.raises(NotPlainError, match=reason):
        plain_many_to_many(_rel(model, name))


# --------------------------------------------------------------------------- edge cases


class _Base(DeclarativeBase):
    pass


class _A(_Base):
    __tablename__ = "edge_a"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)


class _B(_Base):
    __tablename__ = "edge_b"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)


class _Dated(_Base):
    __tablename__ = "edge_dated"
    day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)


class _Pair(_Base):
    __tablename__ = "edge_pair"
    k1: Mapped[int] = mapped_column(primary_key=True)
    k2: Mapped[int] = mapped_column(primary_key=True)


_unique = Table(
    "edge_unique",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), nullable=False),
    Column("b_id", ForeignKey("edge_b.id"), nullable=False),
    UniqueConstraint("a_id", "b_id"),
)
_indexed = Table(
    "edge_indexed",
    _Base.metadata,
    Column("id", Integer, primary_key=True),  # a surrogate key the database numbers
    Column("a_id", ForeignKey("edge_a.id"), nullable=False),
    Column("b_id", ForeignKey("edge_b.id"), nullable=False),
    Index("edge_indexed_pair", "a_id", "b_id", unique=True),
)
_by_code = Table(
    "edge_by_code",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), primary_key=True),
    Column("b_code", ForeignKey("edge_b.code"), primary_key=True),
)
_no_fk = Table(
    "edge_no_fk",
    _Base.metadata,
    Column("a_id", Integer, primary_key=True),
    Column("b_id", Integer, primary_key=True),
)
_third_fk = Table(
    "edge_third_fk",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), primary_key=True),
    Column("b_id", ForeignKey("edge_b.id"), primary_key=True),
    Column("other_id", ForeignKey("edge_a.id"), nullable=True),
)
_dated = Table(
    "edge_dated_links",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), primary_key=True),
    Column("day", ForeignKey("edge_dated.day"), primary_key=True),
)
_pairs = Table(
    "edge_pairs",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), primary_key=True),
    Column("k1", Integer, primary_key=True),
    Column("k2", Integer, primary_key=True),
    ForeignKeyConstraint(["k1", "k2"], ["edge_pair.k1", "edge_pair.k2"]),
)

_A.unique_bs = relationship(_B, secondary=_unique)
_A.indexed_bs = relationship(_B, secondary=_indexed, overlaps="unique_bs")
_A.coded_bs = relationship(_B, secondary=_by_code)
_A.loose_bs = relationship(
    _B,
    secondary=_no_fk,
    primaryjoin=_A.id == _no_fk.c.a_id,
    secondaryjoin=_B.id == _no_fk.c.b_id,
    foreign_keys=[_no_fk.c.a_id, _no_fk.c.b_id],
)
_A.third_bs = relationship(
    _B,
    secondary=_third_fk,
    primaryjoin=_A.id == _third_fk.c.a_id,
    secondaryjoin=_B.id == _third_fk.c.b_id,
)
_A.days = relationship(_Dated, secondary=_dated)
_A.pairs = relationship(_Pair, secondary=_pairs)
configure_mappers()


def test_unique_constraint_or_index_counts_as_unique_pair() -> None:
    assert plain_many_to_many(_rel(_A, "unique_bs")).unique_pair is True
    indexed = plain_many_to_many(_rel(_A, "indexed_bs"))  # integer surrogate key is defaulted
    assert indexed.unique_pair is True


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("coded_bs", "single-column primary keys"),
        ("loose_bs", "must be foreign keys"),
        ("third_bs", "another foreign key"),
        ("days", r"target primary key type \(date\) is not supported"),
        ("pairs", "more than one column pair"),
    ],
)
def test_edge_cases_are_not_plain(name: str, reason: str) -> None:
    with pytest.raises(NotPlainError, match=reason):
        plain_many_to_many(_rel(_A, name))


# --------------------------------------------------------------------------- inheritance


class _Member(_Base):
    __tablename__ = "edge_members"
    __mapper_args__ = {"polymorphic_on": "kind", "polymorphic_identity": "member"}  # noqa: RUF012
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))


class _Staff(_Member):
    """Single-table subclass: its rows are filtered by `kind` only when loading."""

    __mapper_args__ = {"polymorphic_identity": "staff"}  # noqa: RUF012


_team_staff = Table(
    "edge_team_staff",
    _Base.metadata,
    Column("a_id", ForeignKey("edge_a.id"), primary_key=True),
    Column("member_id", ForeignKey("edge_members.id"), primary_key=True),
)
_A.staff = relationship(_Staff, secondary=_team_staff)
_A.members = relationship(_Member, secondary=_team_staff, overlaps="staff")
configure_mappers()


def test_single_table_subclass_target_is_not_plain() -> None:
    """Direct writes would bypass the discriminator filter (any member could be linked)."""
    with pytest.raises(NotPlainError, match="single-table inheritance"):
        plain_many_to_many(_rel(_A, "staff"))


def test_inheritance_base_target_is_plain() -> None:
    assert plain_many_to_many(_rel(_A, "members")).target_model is _Member
