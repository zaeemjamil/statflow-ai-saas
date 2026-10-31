"""
Error-handling foundation.

Every error the API returns — whether raised deliberately by application
code or an unhandled bug — goes through one of the handlers registered
here, so the response shape is always the same `ErrorResponse` schema and
a raw stack trace is never sent to a client (Phase 1 §"Error Handling").

Route/service code should raise one of the `AppException` subclasses
below rather than returning ad-hoc HTTPExceptions, so error codes stay
consistent as new endpoints are added in later phases.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger("zaimex")


class AppException(Exception):
    """Base for all deliberately-raised application errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        # Optional machine-readable context (e.g. {"limit": 100000}) so a
        # client can branch on or display numbers without parsing `message`.
        self.details = details
        if error_code:
            self.error_code = error_code
        super().__init__(message)


class NotFoundException(AppException):
    """A resource doesn't exist — including when it exists but belongs to
    another user. See requirement #9: existence is never confirmed for a
    resource the caller doesn't own, so this and "doesn't exist at all"
    must be indistinguishable from the outside."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ValidationException(AppException):
    """Request data was well-formed JSON/schema but fails a business rule
    (e.g. a regression target column that isn't numeric)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "validation_error"


class UnauthorizedException(AppException):
    """No valid credentials were supplied."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class ConflictException(AppException):
    """The request conflicts with existing state (e.g. duplicate email)."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class PayloadTooLargeException(AppException):
    """The request itself was refused for being too large (e.g. an
    upload over MAX_UPLOAD_SIZE_MB) — distinct from ValidationException:
    this is about how much data was sent, not whether the data received
    was semantically valid, and a client can reasonably branch on the
    difference (413 means "send less data", 422 means "send different
    data")."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    error_code = "payload_too_large"


class TooManyRequestsException(AppException):
    """A per-user or per-resource usage limit was hit (e.g. AI generations)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "too_many_requests"


class BadGatewayException(AppException):
    """An upstream service (e.g. the AI provider) failed or answered badly."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "bad_gateway"


class ServiceUnavailableException(AppException):
    """A feature that needs server-side setup is not configured."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "service_unavailable"


def _error_response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    # `details` is omitted entirely when absent so every pre-existing error
    # response keeps exactly its old shape (API compatibility).
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body, exclude_none=True))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Collapse FastAPI's default (verbose, field-path-heavy) shape into
        # the same ErrorResponse contract every other error uses.
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = str(first.get("msg", "Invalid request"))
        detail = f"{field}: {msg}" if field else msg
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        settings = get_settings()
        message = str(exc) if not settings.is_production else "An unexpected error occurred."
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", message)
