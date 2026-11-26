"""``Admin(sync_permissions_on_startup=True)`` (ADR-0012 §5; private).

Mounted sub-apps get no lifespan events, so the sync runs on the first HTTP
request to the admin, once, under a lock created in the running loop. It
never prunes. Several processes starting at once insert the same codenames
concurrently: duplicates are skipped by the insert itself, and a deadlock or
serialization failure (e.g. an InnoDB deadlock victim) is retried after a
short backoff, a few times within about 2 seconds, without logging. Any other
failure, including a lock-wait timeout, is logged (type only) and retried on
a later request after RETRY_INTERVAL; requests are served meanwhile, and
missing permissions simply grant nothing.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from faststudio.api._db_errors import is_lost_race
from faststudio.api._escalation import EscalationRules
from faststudio.api._permission_sync import apply_sync, plan_sync
from faststudio.registry import Registry

logger = logging.getLogger("faststudio")

#: Seconds between attempts after a failed sync.
RETRY_INTERVAL = 30.0
#: Attempts when the sync loses a race to another process (deadlock victim).
RACE_ATTEMPTS = 5
#: No new attempt starts later than this many seconds after the first one.
RACE_BUDGET = 2.0
_sleep = asyncio.sleep  # tests replace this one name, not asyncio.sleep


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
        #: Monotonic time before which a failed sync is not retried.
        self._retry_after = 0.0

    async def _sync(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()  # inside the running loop
        async with self._lock:
            if self.done or time.monotonic() < self._retry_after:
                return
            try:
                await self._attempt()
            except Exception as exc:
                logger.warning("Permission sync failed (%s); retrying later.", type(exc).__name__)
                # While the database is down, only one request at a time pays for an attempt.
                self._retry_after = time.monotonic() + RETRY_INTERVAL
                return
            self.done = True

    async def _attempt(self) -> None:
        attempt = 1
        started = time.monotonic()
        while True:
            try:
                async with self._session_maker() as session, session.begin():
                    plan = await plan_sync(session, self._rules, self._registry)
                    await apply_sync(session, self._rules, plan, prune=False)
            except StatementError as exc:
                delay = 0.05 * 2 ** (attempt - 1) * (1 + secrets.randbelow(1000) / 1000)
                over_budget = time.monotonic() + delay - started > RACE_BUDGET
                if attempt >= RACE_ATTEMPTS or over_budget or not is_lost_race(exc):
                    raise
                await _sleep(delay)  # another process won; back off with jitter
                if time.monotonic() - started > RACE_BUDGET:
                    raise  # the wait took longer than planned: no new attempt
                attempt += 1
            else:
                return

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Sync before the first HTTP request, then pass everything through."""
        if scope["type"] == "http" and not self.done:
            await self._sync()
        await self._app(scope, receive, send)
