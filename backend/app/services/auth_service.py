"""
Auth business logic. Routers call these; these raise
`app.core.exceptions.AppException` subclasses directly rather than
returning error codes for the router to translate, matching the
convention every other service in this codebase follows.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import _DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.models import PasswordResetToken, User
from app.services.email_service import EmailProvider

# Generic messages — deliberately identical regardless of *why* login or
# a reset request "failed", so a response never tells a caller whether
# an email belongs to an account (requirement: no account enumeration).
_INVALID_LOGIN_MESSAGE = "Invalid email or password."
_GENERIC_RESET_REQUEST_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)
_INVALID_RESET_TOKEN_MESSAGE = "This password reset link is invalid or has expired."


def register_user(db: Session, *, email: str, password: str, full_name: str | None) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictException(
            "An account with this email already exists.", error_code="email_taken"
        )

    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The proactive check above has a race window between two
        # concurrent registrations for the same email - the database's
        # unique constraint (Phase 4) is the actual source of truth, so
        # this is the real guard, not just belt-and-suspenders.
        db.rollback()
        raise ConflictException(
            "An account with this email already exists.", error_code="email_taken"
        ) from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    """Raises UnauthorizedException with the same message whether the
    email doesn't exist or the password is wrong — distinguishing them
    would let a caller enumerate registered accounts.

    `verify_password` always runs, even when no user was found: Argon2
    is deliberately slow, so skipping it via short-circuit evaluation
    when `user is None` would make "no such account" measurably faster
    than "wrong password on a real account" — a timing side-channel that
    leaks exactly the account-existence information the identical
    response body is meant to hide.
    """
    user = db.scalar(select(User).where(User.email == email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(password, password_hash)
    if user is None or not password_matches:
        raise UnauthorizedException(_INVALID_LOGIN_MESSAGE, error_code="invalid_credentials")
    return user


def _hash_reset_token(raw_token: str) -> str:
    # SHA-256, not Argon2: this hashes a 256-bit random token, not a
    # user-chosen password. There's no low-entropy input to defend
    # against by slowing the hash down — a fast, deterministic hash is
    # both correct and sufficient here, and lets lookup-by-hash use a
    # plain indexed equality query.
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def request_password_reset(
    db: Session, *, email: str, email_provider: EmailProvider, settings: Settings
) -> None:
    """Always completes the same way regardless of whether the email
    belongs to an account — the caller (the API layer) returns the same
    generic response either way. Nothing about account existence is
    observable from this function's *return value*.

    Timing: token generation + hashing runs unconditionally, before the
    existence check, rather than only on the found-user branch — this
    equalizes the (small) CPU-bound cost of this step regardless of
    outcome, the same principle as authenticate_user's dummy-hash check,
    just applied to a cheaper operation. What's *not* equalized is the
    DB write + email dispatch that only happens for a real account —
    deliberately: faking a DB insert for a nonexistent email would mean
    either writing a row with no real user to attach it to, or an
    artificial delay that needs constant re-tuning as the real cost
    changes, both of which are more complexity than this risk currently
    justifies. With today's LoggingEmailProvider that gap is a single
    fast DB commit and a log call — measured directly against both this
    codebase's SQLite test database and a real local Postgres instance
    (100+ calls each): roughly 1ms and 2ms respectively, versus roughly
    0.15-0.3ms for the nonexistent-email path. A couple of milliseconds
    is small next to realistic network jitter for an actual client, so
    it's a real but low-value signal today. It becomes worth revisiting
    once a real (network-bound) email provider lands, at which point the
    fix is to stop waiting on that call in the request/response cycle
    (dispatch it via a background task) rather than trying to fake its
    latency for the nonexistent-email path.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_reset_token(raw_token)

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC)
        + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(reset_token)
    db.commit()

    email_provider.send_password_reset_email(to_email=user.email, reset_token=raw_token)


def _as_aware_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes for DateTime(timezone=True) columns
    even though the same column is genuinely timezone-aware on Postgres
    (no real timestamptz type in SQLite). Comparing a naive value against
    an aware `datetime.now(timezone.utc)` raises TypeError, so anything
    read back from the DB is normalized here before comparison rather
    than assuming a particular backend's round-trip behavior."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def reset_password(db: Session, *, raw_token: str, new_password: str) -> None:
    token_hash = _hash_reset_token(raw_token)
    reset_token = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )

    now = datetime.now(UTC)
    if (
        reset_token is None
        or reset_token.used_at is not None
        or _as_aware_utc(reset_token.expires_at) < now
    ):
        # Same message whether the token is unknown, already used, or
        # expired — distinguishing them gives an attacker a guessing
        # oracle for valid-but-expired tokens.
        raise UnauthorizedException(_INVALID_RESET_TOKEN_MESSAGE, error_code="invalid_reset_token")

    user = db.get(User, reset_token.user_id)
    if user is None:
        # The user was deleted after requesting a reset. Same generic
        # message — nothing here should distinguish "deleted account"
        # from "bad token" to the caller.
        raise UnauthorizedException(_INVALID_RESET_TOKEN_MESSAGE, error_code="invalid_reset_token")

    user.password_hash = hash_password(new_password)

    # Invalidate every outstanding reset token for this user, not just
    # the one used — if several reset emails were requested, only this
    # action should remain live afterward.
    other_tokens = db.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    for token in other_tokens:
        token.used_at = now

    db.commit()


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


__all__ = [
    "register_user",
    "authenticate_user",
    "request_password_reset",
    "reset_password",
    "get_user_by_id",
]
