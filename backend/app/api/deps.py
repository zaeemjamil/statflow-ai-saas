"""
Shared FastAPI dependencies for the API layer. `get_current_user` is
what every future protected route (projects, files, reports) depends
on to reliably identify the authenticated user - it's the one place
that turns a session cookie into a real User row, so ownership checks
downstream (`project.user_id == current_user.id`) always have a
database-backed user to compare against, never just a decoded claim.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, build_provider
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedException
from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_token
from app.models import User
from app.services.auth_service import get_user_by_id
from app.services.storage_service import StorageService, get_storage_service


def get_storage(settings: Settings = Depends(get_settings)) -> StorageService:
    return get_storage_service(settings)


def get_ai_provider(settings: Settings = Depends(get_settings)) -> AIProvider | None:
    """None when no API key is configured (AI endpoints then answer 503)."""
    return build_provider(settings)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(settings.COOKIE_NAME)
    if token is None:
        raise UnauthorizedException("Not authenticated.", error_code="missing_token")

    try:
        user_id = decode_access_token(token, settings)
    except TokenExpiredError as exc:
        raise UnauthorizedException(
            "Your session has expired. Please log in again.", error_code="token_expired"
        ) from exc
    except TokenInvalidError as exc:
        raise UnauthorizedException(
            "Could not validate credentials.", error_code="invalid_token"
        ) from exc

    user = get_user_by_id(db, user_id)
    if user is None:
        # The token is cryptographically valid, but the account it
        # names doesn't exist anymore (e.g. deleted after issuance) -
        # fail safely with the same generic error, not a 500.
        raise UnauthorizedException("Could not validate credentials.", error_code="invalid_token")

    return user
