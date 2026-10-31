from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import AppException, TooManyRequestsException
from app.core.security import create_access_token
from app.core.throttle import login_limiter, reset_limiter
from app.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    UserPublic,
)
from app.services import auth_service
from app.services.email_service import BackgroundEmailProvider, get_email_provider

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id: uuid.UUID, settings: Settings) -> None:
    token = create_access_token(user_id, settings)
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )


@router.post("/register", response_model=UserPublic, status_code=201)
def register(
    body: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    user = auth_service.register_user(
        db, email=body.email, password=body.password, full_name=body.full_name
    )
    # Phase 2 §2 (approved UX spec): signup goes straight to the
    # dashboard, not a separate login screen - so registration issues
    # the same session cookie login does, rather than requiring the
    # frontend to immediately call /login again with the same
    # credentials it just collected.
    _set_session_cookie(response, user.id, settings)
    return user


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=UserPublic)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    window = settings.LOGIN_LOCKOUT_MINUTES * 60.0
    email_key = f"email:{body.email.strip().lower()}"
    ip_key = f"ip:{_client_ip(request)}"
    for key, limit in (
        (email_key, settings.LOGIN_MAX_FAILURES),
        (ip_key, settings.LOGIN_MAX_FAILURES * 5),
    ):
        wait = login_limiter.retry_after(key, limit=limit, window=window)
        if wait:
            raise TooManyRequestsException(
                "Too many failed sign-in attempts. Please wait a few minutes and try again.",
                error_code="too_many_login_attempts",
                details={"retry_after_seconds": wait},
            )
    try:
        user = auth_service.authenticate_user(db, email=body.email, password=body.password)
    except AppException:
        login_limiter.record(email_key, window=window)
        login_limiter.record(ip_key, window=window)
        raise
    login_limiter.reset(email_key)
    # The token lives only in the HttpOnly cookie, never in the JSON
    # body - putting it in both would let JS read it from the response
    # even though it can't read the cookie itself, defeating the point.
    _set_session_cookie(response, user.id, settings)
    return user


@router.post("/logout", response_model=MessageResponse)
def logout(response: Response, settings: Settings = Depends(get_settings)) -> MessageResponse:
    # Deliberately does not require get_current_user: clearing a
    # stale/expired/already-missing cookie should always succeed rather
    # than erroring, since the caller's goal ("make sure I'm logged
    # out") is satisfied either way. See the Phase 5 report's
    # "Cookie/JWT design" section for the full logout-model reasoning.
    #
    # secure/samesite are passed explicitly rather than left at
    # delete_cookie's own defaults (secure=False, samesite='lax')
    # because those don't track how the cookie was actually configured
    # at login - in a real cross-origin deployment (COOKIE_SAMESITE=
    # none), the defaults would send a clearing cookie with different
    # attributes than the one being cleared.
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=UserPublic)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    window = 3600.0
    keys = (
        (f"email:{body.email.strip().lower()}", settings.PASSWORD_RESET_MAX_PER_HOUR),
        (f"ip:{_client_ip(request)}", settings.PASSWORD_RESET_MAX_PER_HOUR * 4),
    )
    throttled = any(reset_limiter.retry_after(k, limit=n, window=window) for k, n in keys)
    for k, _ in keys:
        reset_limiter.record(k, window=window)
    if not throttled:
        auth_service.request_password_reset(
            db,
            email=body.email,
            email_provider=BackgroundEmailProvider(get_email_provider(settings), tasks),
            settings=settings,
        )
    # Same message whether or not the email belongs to an account, and whether or
    # not this request was throttled (so neither fact can be probed).
    return MessageResponse(
        message="If an account exists for that email, a password reset link has been sent."
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    auth_service.reset_password(db, raw_token=body.token, new_password=body.new_password)
    return MessageResponse(message="Your password has been reset.")
