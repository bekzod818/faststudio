"""`POST /auth/sign-out-everywhere` (ADR-0013; threat model T1).

Offered only when the auth backend provides `session_revocation` (404
otherwise). The backend rotates the account's session token, which is part
of its `auth_version`, so every session of the account ends: other
browsers on their next request, this one at once (its cookie is cleared
like on logout).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from faststudio.api._deps import DbSession
from faststudio.api._paths import API_PREFIX
from faststudio.api.auth import CurrentUser, current_user, ended_session_cookies, get_context
from faststudio.api.errors import ApiError
from faststudio.api.write import writing

logger = logging.getLogger("faststudio.auth")

#: Session only: the account is the signed-in user's own.
router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])


@router.post("/auth/sign-out-everywhere", status_code=204)
async def sign_out_everywhere(request: Request, user: CurrentUser, session: DbSession) -> Response:
    """End every session of the signed-in admin, this one included."""
    context = get_context(request)
    revocation = context.capabilities.session_revocation
    if revocation is None:
        raise ApiError(404, "not_found")
    async with writing(session, "accounts", "sign out everywhere"):
        try:
            await revocation.rotate_session_token(session, user.id)
        except LookupError:  # deleted meanwhile: its sessions are dead anyway
            raise ApiError(
                401, "not_authenticated", set_cookies=ended_session_cookies(request)
            ) from None
        await session.flush()
    logger.info("Account %s signed out everywhere", user.id)
    response = Response(status_code=204)
    for cookie in ended_session_cookies(request):
        response.headers.append("set-cookie", cookie)
    return response
