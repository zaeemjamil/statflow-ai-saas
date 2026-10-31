"""
Password hashing and JWT helpers. Pure functions only - no FastAPI,
no database, no Request/Response - so they're unit-testable in
isolation and reusable by any future auth-adjacent code.

Password hashing: Argon2id via argon2-cffi (OWASP's current first
recommendation for new systems, ahead of bcrypt) - not hand-rolled, per
the "do not invent custom cryptography" requirement.

JWT: PyJWT, the standard, maintained library for this in Python.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import Settings

_password_hasher = PasswordHasher()

# Computed once at import time using the same hasher/parameters as real
# passwords, so verifying against it costs the same CPU time as a real
# verification - this is what lets authenticate_user() run a full
# Argon2 check even when no user was found, instead of the timing
# side-channel a short-circuit would create.
_DUMMY_PASSWORD_HASH = _password_hasher.hash("no-such-user-timing-safety-placeholder")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    """Minimum claims only: `sub` (user id) and the standard `exp`/`iat`.
    No email or role is embedded - `get_current_user` always re-fetches
    the user from the database anyway (required, so a deleted user is
    correctly rejected even with a still-cryptographically-valid token),
    so there's no performance reason to duplicate data into the token
    that would just go stale if it changed."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class TokenError(Exception):
    """Common base so callers can catch either specific case generically
    if they don't need to distinguish them."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    """Malformed, bad signature, or missing/invalid required claims -
    every non-expiry failure mode collapses to this one type, since the
    caller treats them identically (a generic "could not validate
    credentials", never detail on which specific check failed)."""


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Returns the user id from a valid token, or raises TokenExpiredError
    / TokenInvalidError."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Invalid token") from exc

    subject = payload.get("sub")
    if not subject:
        raise TokenInvalidError("Token is missing the required 'sub' claim")

    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise TokenInvalidError("Token 'sub' claim is not a valid user id") from exc
