"""Unit tests for app/core/security.py - password hashing and JWT
primitives in isolation, no HTTP/database involved. Endpoint-level
behavior lives in test_auth.py."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
        JWT_SECRET="test-secret-at-least-32-characters-long",
    )


# --- password hashing ---------------------------------------------------


def test_hash_password_does_not_return_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_hash_password_produces_an_argon2id_hash() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")


def test_verify_password_accepts_the_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_the_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hashing_the_same_password_twice_gives_different_hashes() -> None:
    # Argon2 salts automatically - two hashes of the same password must
    # differ, or salting isn't actually happening.
    assert hash_password("same password") != hash_password("same password")


# --- JWT -----------------------------------------------------------------


def test_access_token_round_trips_the_user_id(settings: Settings) -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, settings)
    assert decode_access_token(token, settings) == user_id


def test_decode_rejects_a_token_signed_with_a_different_secret(settings: Settings) -> None:
    token = create_access_token(uuid.uuid4(), settings)
    other_settings = settings.model_copy(update={"JWT_SECRET": "a-completely-different-secret!!!"})
    with pytest.raises(TokenInvalidError):
        decode_access_token(token, other_settings)


def test_decode_rejects_garbage(settings: Settings) -> None:
    with pytest.raises(TokenInvalidError):
        decode_access_token("not-a-real-token", settings)


def test_decode_rejects_a_token_missing_the_subject_claim(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=5)},  # no "sub"
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(TokenInvalidError):
        decode_access_token(token, settings)


def test_decode_raises_expired_error_for_an_expired_token(settings: Settings) -> None:
    now = datetime.now(UTC)
    expired_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(TokenExpiredError):
        decode_access_token(expired_token, settings)


def test_access_token_expiry_follows_settings(settings: Settings) -> None:
    short_settings = settings.model_copy(update={"JWT_EXPIRE_MINUTES": 5})
    token = create_access_token(uuid.uuid4(), short_settings)
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC)
    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    assert (expires_at - issued_at) == timedelta(minutes=5)


def test_access_token_contains_only_minimum_claims(settings: Settings) -> None:
    token = create_access_token(uuid.uuid4(), settings)
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert set(payload.keys()) == {"sub", "iat", "exp"}


# --- production config validation --------------------------------------


def test_production_rejects_the_placeholder_jwt_secret() -> None:
    with pytest.raises(Exception, match="JWT_SECRET"):
        Settings(
            DATABASE_URL="postgresql://u:p@localhost:5432/db",
            ENVIRONMENT="production",
        )


def test_production_rejects_a_too_short_jwt_secret() -> None:
    with pytest.raises(Exception, match="JWT_SECRET"):
        Settings(
            DATABASE_URL="postgresql://u:p@localhost:5432/db",
            ENVIRONMENT="production",
            JWT_SECRET="short",
        )


def test_production_accepts_a_strong_jwt_secret() -> None:
    settings = Settings(
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
        ENVIRONMENT="production",
        JWT_SECRET="a" * 32,
        COOKIE_SECURE=True,
        FRONTEND_URL="https://app.example.com",
    )
    assert settings.JWT_SECRET == "a" * 32


def test_production_allows_email_provider_none() -> None:
    # Deliberate: "make email delivery provider-agnostic... do not
    # integrate a specific email vendor yet" is explicit scope for this
    # phase. Blocking production startup over it would force exactly
    # the vendor integration the requirement says to skip.
    # get_email_provider (app/services/email_service.py) already fails
    # loudly and specifically the moment anything actually tries to use
    # an unimplemented provider - that's the right place for this
    # concern to surface, not a blanket refusal to start at all.
    settings = Settings(
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
        ENVIRONMENT="production",
        JWT_SECRET="a" * 32,
        COOKIE_SECURE=True,
        FRONTEND_URL="https://app.example.com",
    )
    assert settings.EMAIL_PROVIDER == "none"


def test_development_allows_the_placeholder_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # The production-only validator must not block a normal dev
    # checkout that hasn't set a real secret yet. conftest.py sets
    # ENVIRONMENT=test in os.environ for the whole session (env vars
    # always win over field defaults), so the class default is only
    # observable with that var explicitly absent here.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(DATABASE_URL="postgresql://u:p@localhost:5432/db", _env_file=None)
    assert settings.ENVIRONMENT == "development"
