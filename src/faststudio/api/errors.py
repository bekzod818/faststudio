"""Contract error responses (`{"error": {"code", "message", "details"}}`)."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import StatementError
from starlette.exceptions import HTTPException as StarletteHTTPException

from faststudio.schemas.contract import ErrorBody, ErrorCode, ErrorResponse, ValidationIssue

if TYPE_CHECKING:
    from faststudio._spa import SpaSite

logger = logging.getLogger("faststudio.api")

_MESSAGES: dict[ErrorCode, str] = {
    "invalid_query": "Invalid request.",
    "not_authenticated": "Authentication required.",
    "invalid_credentials": "Invalid username or password.",
    "csrf_failed": "CSRF validation failed.",
    "forbidden": "Forbidden.",
    "not_found": "Not found.",
    "method_not_allowed": "Method not allowed.",
    "conflict": "Conflict.",
    "validation_error": "Invalid input.",
    "payload_too_large": "Request body too large.",
    "rate_limited": "Too many requests.",
    "internal_error": "Internal server error.",
}
_STATUS_CODES: dict[int, ErrorCode] = {
    400: "invalid_query",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}
_SAFE_METHODS = frozenset({"GET", "HEAD"})
_NOT_FOUND = 404
_SERVER_ERROR = 500
# 422 bodies may contain client-chosen keys in `loc`; bound their size.
_MAX_ISSUES = 50
_MAX_LOC_PART = 64


class ApiError(Exception):
    """Raise from FastStudio routes to return a contract error."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        set_cookies: Sequence[str] = (),
        details: list[ValidationIssue] | None = None,
    ) -> None:
        """Create an error; `message` defaults to a generic text for `code`."""
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message or _MESSAGES[code]
        self.headers = headers
        self.set_cookies = tuple(set_cookies)
        self.details = details


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str | None = None,
    *,
    details: list[ValidationIssue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a contract error response. Messages are generic unless given."""
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message or _MESSAGES[code], details=details)
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


def _loc_part(part: object) -> str | int:
    if isinstance(part, int) and not isinstance(part, bool):
        return part
    text = str(part)
    return text if len(text) <= _MAX_LOC_PART else text[: _MAX_LOC_PART - 1] + "…"


def validation_issues(errors: Sequence[Mapping[str, object]]) -> list[ValidationIssue]:
    """Reduce pydantic errors to `loc`/`msg`/`type`.

    Submitted values (`input`, `ctx`) are dropped. `loc` can contain
    client-chosen keys (e.g. unknown body fields), so each part is truncated
    and at most `_MAX_ISSUES` issues are returned.
    """
    issues: list[ValidationIssue] = []
    for error in errors[:_MAX_ISSUES]:
        loc = error.get("loc", ())
        parts = loc if isinstance(loc, tuple | list) else (loc,)
        issues.append(
            ValidationIssue(
                loc=[_loc_part(part) for part in parts],
                msg=str(error.get("msg", "")),
                type=str(error.get("type", "")),
            )
        )
    return issues


def install_error_handlers(app: FastAPI, site: SpaSite) -> None:
    """Route every error through the contract format; unmatched GETs render the SPA."""

    # Starlette dispatches handlers by exception type, so the casts are safe.
    async def on_api_error(request: Request, exc: Exception) -> Response:
        error = cast("ApiError", exc)
        response = error_response(
            error.status_code,
            error.code,
            error.message,
            details=error.details,
            headers=error.headers,
        )
        for cookie in error.set_cookies:
            response.headers.append("set-cookie", cookie)
        return response

    async def on_http_error(request: Request, exc: Exception) -> Response:
        http_error = cast("StarletteHTTPException", exc)
        status = http_error.status_code
        if status == _NOT_FOUND:
            fallback = site.fallback(request)
            if fallback is not None:
                return fallback
            if request.method not in _SAFE_METHODS and not site.is_reserved(request):
                return error_response(405, "method_not_allowed", headers={"Allow": "GET, HEAD"})
        default: ErrorCode = "internal_error" if status >= _SERVER_ERROR else "invalid_query"
        headers = dict(http_error.headers) if http_error.headers else None
        return error_response(status, _STATUS_CODES.get(status, default), headers=headers)

    async def on_validation_error(request: Request, exc: Exception) -> Response:
        errors = cast("RequestValidationError", exc).errors()
        return error_response(422, "validation_error", details=validation_issues(errors))

    async def on_unhandled(request: Request, exc: Exception) -> Response:
        # Starlette re-raises after this response is sent, so host error handlers
        # and monitoring still see admin failures (documented in ADR-0008).
        if isinstance(exc, StatementError):
            # Database errors embed the SQL and its parameters (row values):
            # log only the error types.
            logger.error(
                "Database error in %s %s: %s (%s)",
                request.method,
                request.url.path,
                type(exc).__name__,
                type(exc.orig).__name__,
            )
        else:
            logger.error("Unhandled error in %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(500, "internal_error")

    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(StarletteHTTPException, on_http_error)
    app.add_exception_handler(RequestValidationError, on_validation_error)
    app.add_exception_handler(Exception, on_unhandled)
