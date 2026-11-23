"""Shared FastAPI dependencies for admin API routes (private)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from faststudio.api.auth import get_context
from faststudio.api.errors import ApiError
from faststudio.registry import RegisteredModel


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request."""
    async with get_context(request).session_maker() as session:
        yield session


def registered_model(identity: str, request: Request) -> RegisteredModel:
    """Look up a model by identity; unknown identities are 404."""
    try:
        return get_context(request).registry.get(identity)
    except KeyError:
        raise ApiError(404, "not_found") from None


DbSession = Annotated[AsyncSession, Depends(db_session)]
ModelDep = Annotated[RegisteredModel, Depends(registered_model)]
