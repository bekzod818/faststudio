"""``Admin(sync_permissions_on_startup=True)`` (ADR-0012 §5; private).

Mounted sub-apps get no lifespan events, so the sync runs on the first HTTP
request to the admin, once, under a lock created in the running loop. It
never prunes. A failure is logged (type only) and retried on a later request;
requests are served meanwhile, and missing permissions simply grant nothing.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from faststudio.api._escalation import EscalationRules
from faststudio.api._permission_sync import apply_sync, plan_sync
from faststudio.registry import Registry

logger = logging.getLogger("faststudio")


class StartupPermissionSync:
    """ASGI wrapper around the admin that synchronizes permissions once."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        rules: EscalationRules,
        registry: Registry,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        """Wrap `app`; nothing runs until the first HTTP request."""
        self._app = app
        self._rules = rules
        self._registry = registry
        self._session_maker = session_maker
        self._lock: asyncio.Lock | None = None
        self.done = False

    async def _sync(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()  # inside the running loop
        async with self._lock:
            if self.done:
                return
            try:
                async with self._session_maker() as session, session.begin():
                    plan = await plan_sync(session, self._rules, self._registry)
                    await apply_sync(session, self._rules, plan, prune=False)
            except Exception as exc:
                logger.warning("Permission sync failed (%s); retrying later.", type(exc).__name__)
                return
            self.done = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Sync before the first HTTP request, then pass everything through."""
        if scope["type"] == "http" and not self.done:
            await self._sync()
        await self._app(scope, receive, send)
