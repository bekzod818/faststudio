"""Models for the contrib.auth tests: the auth tables plus one content model."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from faststudio.contrib.auth import AuthModels


class ContribBase(DeclarativeBase):
    pass


AUTH = AuthModels(ContribBase)


class Note(ContribBase):
    __tablename__ = "contrib_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
