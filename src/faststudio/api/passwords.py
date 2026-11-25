"""Password endpoints (ADR-0013; threat model T2).

Both are offered only when the auth backend provides `accounts` and enables
`password_endpoints` (404 otherwise). Passwords never appear in responses,
errors or logs.

- `POST /auth/password` changes one's own password. The current password is
  required and checked in constant time; wrong guesses count against the
  login rate limiters. Success revokes every other session of the account
  (the hash is part of `auth_version`) and re-issues the current one.
- `POST /models/{identity}/items/{pk}/password` sets another account's
  password. It needs every permission and is never for one's own account.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from faststudio.api._authz import allowed, resolve_permissions
from faststudio.api._deps import DbSession, ModelDep
from faststudio.api._paths import API_PREFIX
from faststudio.api._records import load_or_404
from faststudio.api.auth import (
    CurrentUser,
    cookie_path,
    current_user,
    get_context,
    rate_limit_username,
)
from faststudio.api.errors import ApiError
from faststudio.api.write import writing
from faststudio.auth.capabilities import AccountManager, AllPermissions
from faststudio.auth.cookies import csrf_cookie, session_cookie
from faststudio.auth.permissions import cached_permissions
from faststudio.auth.validators import validate_password
from faststudio.schemas.contract import ChangePasswordRequest, SetPasswordRequest, ValidationIssue

logger = logging.getLogger("faststudio.auth")

#: Session only: the account is the signed-in user's own.
own_router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(current_user)])
#: A model route: permissions are resolved like every other (route test).
router = APIRouter(
    prefix=API_PREFIX, dependencies=[Depends(current_user), Depends(resolve_permissions)]
)


def _accounts(request: Request) -> AccountManager:
    capabilities = get_context(request).capabilities
    if not capabilities.password_endpoints or capabilities.accounts is None:
        raise ApiError(404, "not_found")
    return capabilities.accounts


def _invalid(field: str, messages: list[str], kind: str) -> ApiError:
    issues = [ValidationIssue(loc=[field], msg=message, type=kind) for message in messages]
    return ApiError(422, "validation_error", details=issues)


async def _check_new(
    accounts: AccountManager, session: DbSession, account_id: str, password: str
) -> None:
    inputs = await accounts.user_inputs(session, account_id)
    messages = validate_password(password, accounts.password_validators, user_inputs=inputs)
    if messages:
        raise _invalid("new_password", messages, "password")


@own_router.post("/auth/password", status_code=204)
async def change_password(
    request: Request, body: ChangePasswordRequest, user: CurrentUser, session: DbSession
) -> Response:
    """Change the signed-in admin's password and re-issue their session."""
    accounts = _accounts(request)
    context = get_context(request)
    client = request.client.host if request.client else "unknown"
    key = f"{client}|{rate_limit_username(user.username)}"
    decision = await context.client_rate_limiter.hit(client)
    if decision.allowed:
        decision = await context.rate_limiter.hit(key)
    if not decision.allowed:
        logger.warning("Password change rate limit reached for client %s", client)
        raise ApiError(429, "rate_limited", headers={"Retry-After": str(decision.retry_after)})
    if not await accounts.check_password(session, user.id, body.current_password):
        logger.info("Wrong current password on a password change from client %s", client)
        raise _invalid("current_password", ["The current password is incorrect."], "invalid")
    if body.new_password == body.current_password:
        raise _invalid("new_password", ["Choose a password you have not used here."], "password")
    await _check_new(accounts, session, user.id, body.new_password)
    # Database errors and lost races map like any write (409, never 500).
    async with writing(session, "accounts", "password change"):
        try:
            await accounts.set_password(session, user.id, body.new_password)
        except LookupError:  # deleted meanwhile
            raise ApiError(404, "not_found") from None
        await session.flush()
    await context.rate_limiter.reset(key)
    # Every session of this account is now stale (new hash, new auth_version):
    # issue a fresh one, and a CSRF token bound to it.
    renewed = await context.auth_backend.get_user(request, user.id)
    if renewed is None:  # deactivated meanwhile
        raise ApiError(401, "not_authenticated")
    value, data = context.sessions.issue(user_id=renewed.id, auth_version=renewed.auth_version)
    path, secure = cookie_path(request), context.settings.secure_cookies
    response = Response(status_code=204)
    response.headers.append(
        "set-cookie",
        session_cookie(value, path=path, max_age=context.sessions.max_age, secure=secure),
    )
    response.headers.append(
        "set-cookie",
        csrf_cookie(context.csrf.issue(session_id=data.session_id), path=path, secure=secure),
    )
    return response


@router.post("/models/{identity}/items/{pk}/password", status_code=204)
async def set_password(  # noqa: PLR0917 - FastAPI dependencies
    request: Request,
    registered: ModelDep,
    pk: str,
    body: SetPasswordRequest,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    """Set another account's password (revokes its sessions).

    Needs every permission, and the model's edit hooks (it is an edit of the
    account): `can_edit = False` or an object-level edit refusal blocks it.
    """
    accounts = _accounts(request)
    guard = get_context(request).capabilities.account_guard
    if guard is None or not guard.guards(registered.model):
        raise ApiError(404, "not_found")
    if not isinstance(cached_permissions(request), AllPermissions):
        raise ApiError(403, "forbidden")
    if not await allowed(request, registered, "edit"):
        raise ApiError(403, "forbidden")  # setting a password is an edit of the account
    obj = await load_or_404(session, registered, pk)
    if not await allowed(request, registered, "view", obj):
        raise ApiError(404, "not_found")  # hidden from retrieve: hidden here too
    if not await allowed(request, registered, "edit", obj):
        raise ApiError(403, "forbidden")
    account_id = str(getattr(obj, registered.pk_field))
    if account_id == user.id:
        raise ApiError(403, "forbidden", "Use POST /auth/password to change your own password.")
    await _check_new(accounts, session, account_id, body.new_password)
    async with writing(session, registered.identity, "set password"):
        try:
            await accounts.set_password(session, account_id, body.new_password)
        except LookupError:
            raise ApiError(404, "not_found") from None
        await session.flush()
    return Response(status_code=204)
