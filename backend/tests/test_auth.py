"""
Endpoint-level auth tests via a real HTTP client (see conftest.py's
`client` fixture - its `get_db` dependency is overridden to the same
SQLite database as `db_session`, so a test can register via HTTP and
then inspect the resulting row directly).

Session cookie handling: `TestClient` keeps its own cookie jar, so after
a successful `_login()`, subsequent requests made with that *same*
client automatically carry the session cookie - no manual header
wiring needed for the common path. Tests that need a specific/invalid
token set `client.cookies.set(...)` directly instead.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PasswordResetToken, User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
FORGOT_PASSWORD_URL = "/api/v1/auth/forgot-password"
RESET_PASSWORD_URL = "/api/v1/auth/reset-password"


def _register(
    client: TestClient, email: str = "ada@example.com", password: str = "correct-horse-1"
) -> dict[str, object]:
    response = client.post(REGISTER_URL, json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


def _login(
    client: TestClient, email: str = "ada@example.com", password: str = "correct-horse-1"
) -> None:
    response = client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200, response.text


# --- registration --------------------------------------------------------


def test_successful_registration(client: TestClient) -> None:
    body = _register(client)
    assert body["email"] == "ada@example.com"
    assert "id" in body
    assert "password_hash" not in body


def test_password_is_hashed_and_never_stored_plaintext(
    client: TestClient, db_session: Session
) -> None:
    _register(client, password="my-plaintext-password")
    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None
    assert user.password_hash != "my-plaintext-password"
    assert user.password_hash.startswith("$argon2id$")


def test_duplicate_email_registration_is_rejected(client: TestClient) -> None:
    _register(client)
    response = client.post(
        REGISTER_URL, json={"email": "ada@example.com", "password": "another-password-1"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_registration_requires_a_minimum_length_password(client: TestClient) -> None:
    response = client.post(REGISTER_URL, json={"email": "short@example.com", "password": "short"})
    assert response.status_code == 422


def test_registration_requires_a_valid_email_format(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL, json={"email": "not-an-email", "password": "a-fine-password-1"}
    )
    assert response.status_code == 422


def test_successful_registration_logs_the_user_in(client: TestClient) -> None:
    # Phase 2 §2 (approved UX spec): signup goes straight to the
    # dashboard, not a separate login screen - so /register must issue
    # the same session cookie /login does.
    settings = get_settings()
    response = client.post(
        REGISTER_URL, json={"email": "grace@example.com", "password": "correct-horse-1"}
    )

    assert response.status_code == 201
    cookie = next(c for c in client.cookies.jar if c.name == settings.COOKIE_NAME)
    assert cookie.value

    me_response = client.get(ME_URL)
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "grace@example.com"


# --- email normalization -------------------------------------------------


def test_email_is_normalized_to_lowercase_on_registration(
    client: TestClient, db_session: Session
) -> None:
    client.post(
        REGISTER_URL, json={"email": "  Ada@Example.COM  ", "password": "a-fine-password-1"}
    )
    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None


def test_login_email_is_normalized_so_different_casing_still_works(client: TestClient) -> None:
    _register(client, email="ada@example.com")
    response = client.post(
        LOGIN_URL, json={"email": "ADA@EXAMPLE.COM", "password": "correct-horse-1"}
    )
    assert response.status_code == 200


# --- login -----------------------------------------------------------------


def test_successful_login_sets_an_httponly_session_cookie(client: TestClient) -> None:
    _register(client)
    settings = get_settings()
    response = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "correct-horse-1"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"
    assert "password_hash" not in response.json()

    cookie = next(c for c in client.cookies.jar if c.name == settings.COOKIE_NAME)
    assert cookie.value  # a real token, not empty
    # httpx's cookiejar exposes HttpOnly via the REST field; presence in
    # the Set-Cookie header is the authoritative check.
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "httponly" in set_cookie_header.lower()
    assert "samesite=lax" in set_cookie_header.lower()


def test_login_response_body_never_contains_the_raw_token(client: TestClient) -> None:
    # The whole point of HttpOnly is that JS can't read the cookie - if
    # the token were *also* in the JSON body, that protection would be
    # moot at the moment of login.
    _register(client)
    response = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "correct-horse-1"}
    )
    assert "access_token" not in response.json()
    assert "token" not in response.json()


def test_wrong_password_is_rejected(client: TestClient) -> None:
    _register(client)
    response = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_nonexistent_user_login_is_rejected(client: TestClient) -> None:
    response = client.post(
        LOGIN_URL, json={"email": "nobody@example.com", "password": "whatever-1"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_failure_messages_are_indistinguishable(client: TestClient) -> None:
    # Account enumeration check: wrong-password and no-such-user must
    # return byte-for-byte the same body, not just the same status code.
    _register(client)
    wrong_password = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "wrong-password"}
    )
    no_such_user = client.post(
        LOGIN_URL, json={"email": "nobody@example.com", "password": "whatever-1"}
    )
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


def test_nonexistent_user_login_still_performs_password_verification(
    db_session: Session,
) -> None:
    # A same-body response isn't enough on its own - if verify_password
    # were skipped for a nonexistent user (it deliberately runs Argon2,
    # which is slow), the *response time* would still leak whether the
    # account exists even though the JSON body doesn't. This asserts the
    # underlying call happens rather than the wall-clock speed, since a
    # timing-based assertion would be flaky under real system load.
    from unittest.mock import patch

    from app.core.exceptions import UnauthorizedException
    from app.services.auth_service import authenticate_user

    with patch("app.services.auth_service.verify_password", return_value=False) as spy:
        with pytest.raises(UnauthorizedException):
            authenticate_user(db_session, email="nobody@example.com", password="whatever-1")

    spy.assert_called_once()


# --- get_current_user / protected routes ----------------------------------


def test_valid_session_cookie_authenticates(client: TestClient) -> None:
    _register(client)
    _login(client)
    response = client.get(ME_URL)
    assert response.status_code == 200


def test_missing_token_is_rejected(client: TestClient) -> None:
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_invalid_token_is_rejected(client: TestClient) -> None:
    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, "not-a-real-token")
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_malformed_jwt_is_rejected(client: TestClient) -> None:
    settings = get_settings()
    # Syntactically JWT-shaped (three dot-separated segments) but garbage.
    client.cookies.set(settings.COOKIE_NAME, "abc.def.ghi")
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_token_signed_with_a_different_secret_is_rejected(client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5)},
        "a-completely-different-secret-nobody-configured",
        algorithm=settings.JWT_ALGORITHM,
    )
    client.cookies.set(settings.COOKIE_NAME, forged)
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_expired_token_is_rejected(client: TestClient) -> None:
    settings = get_settings()
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
    client.cookies.set(settings.COOKIE_NAME, expired_token)
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_token_missing_the_subject_claim_is_rejected(client: TestClient) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=5)},  # no "sub"
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    client.cookies.set(settings.COOKIE_NAME, token)
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_token_for_a_deleted_user_is_rejected(client: TestClient, db_session: Session) -> None:
    _register(client)
    _login(client)

    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None
    db_session.delete(user)
    db_session.commit()

    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_me_returns_the_authenticated_user(client: TestClient) -> None:
    registered = _register(client, email="ada@example.com")
    _login(client)
    response = client.get(ME_URL)
    body = response.json()
    assert body["id"] == registered["id"]
    assert body["email"] == "ada@example.com"


def test_me_never_returns_password_hash(client: TestClient) -> None:
    _register(client)
    _login(client)
    response = client.get(ME_URL)
    assert "password_hash" not in response.json()


def test_protected_route_cannot_be_reached_without_authentication(client: TestClient) -> None:
    # A fresh client with no login and no cookie at all.
    response = client.get(ME_URL)
    assert response.status_code == 401


# --- logout ----------------------------------------------------------------


def test_logout_clears_the_session_cookie(client: TestClient) -> None:
    _register(client)
    _login(client)
    assert client.get(ME_URL).status_code == 200

    logout_response = client.post(LOGOUT_URL)
    assert logout_response.status_code == 200

    # The cookie the browser holds is now cleared - a subsequent request
    # with this same client (same cookie jar) must be unauthenticated.
    assert client.get(ME_URL).status_code == 401


def test_logout_clearing_cookie_matches_the_login_cookies_attributes(client: TestClient) -> None:
    # Regression test: delete_cookie()'s own library defaults
    # (secure=False, samesite='lax') don't track how the app is actually
    # configured. In a real cross-origin deployment (COOKIE_SAMESITE=
    # none), a logout response using those defaults instead of the
    # configured values would clear a cookie with different attributes
    # than the one that was set - caught by inspecting the raw
    # Set-Cookie header here rather than only the functional outcome.
    settings = get_settings()
    _register(client)
    _login(client)

    logout_response = client.post(LOGOUT_URL)
    set_cookie = logout_response.headers.get("set-cookie", "")

    assert "secure" in set_cookie.lower() if settings.COOKIE_SECURE else True
    assert f"samesite={settings.COOKIE_SAMESITE}" in set_cookie.lower()
    assert "max-age=0" in set_cookie.lower()


def test_logout_without_a_prior_login_still_succeeds(client: TestClient) -> None:
    # Clearing an already-absent cookie is not an error - the caller's
    # goal ("be logged out") is already satisfied.
    response = client.post(LOGOUT_URL)
    assert response.status_code == 200


# --- password reset ---------------------------------------------------------


def test_forgot_password_for_existing_email_returns_generic_message_and_creates_a_token(
    client: TestClient, db_session: Session
) -> None:
    _register(client)
    response = client.post(FORGOT_PASSWORD_URL, json={"email": "ada@example.com"})
    assert response.status_code == 200
    assert "if an account exists" in response.json()["message"].lower()

    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None
    token_row = db_session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    assert token_row is not None
    assert token_row.used_at is None


def test_forgot_password_for_nonexistent_email_returns_the_identical_response(
    client: TestClient,
) -> None:
    _register(client)
    real = client.post(FORGOT_PASSWORD_URL, json={"email": "ada@example.com"})
    fake = client.post(FORGOT_PASSWORD_URL, json={"email": "nobody@example.com"})
    assert real.status_code == fake.status_code == 200
    assert real.json() == fake.json()


def test_reset_token_expiry_is_controlled_by_settings(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A value distinctly different from both the default (30) and the
    # old hardcoded bug (60) proves the setting is actually wired
    # through, not just coincidentally plausible.
    monkeypatch.setenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "5")
    get_settings.cache_clear()

    _register(client, email="expiry-test@example.com")
    before = datetime.now(UTC)
    response = client.post(FORGOT_PASSWORD_URL, json={"email": "expiry-test@example.com"})
    assert response.status_code == 200

    user = db_session.scalar(select(User).where(User.email == "expiry-test@example.com"))
    assert user is not None
    token_row = db_session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    assert token_row is not None

    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive, same as Phase 4's tables
        expires_at = expires_at.replace(tzinfo=UTC)

    expected = before + timedelta(minutes=5)
    # Tight tolerance is the point: 60 minutes of hardcoded slack would
    # pass a loose check just as easily as the fix would - only a tight
    # bound actually distinguishes "reads settings" from "still hardcoded".
    assert abs((expires_at - expected).total_seconds()) < 5


def test_reset_password_with_a_valid_token_changes_the_password(
    client: TestClient, db_session: Session
) -> None:
    _register(client)
    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None

    # Exercise the service directly to get the raw token - the API
    # itself never returns it (that's the email provider's job).
    from app.services.auth_service import _hash_reset_token

    raw_token = "a-raw-token-for-testing-only"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()

    response = client.post(
        RESET_PASSWORD_URL, json={"token": raw_token, "new_password": "brand-new-password-1"}
    )
    assert response.status_code == 200

    old_login = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "correct-horse-1"}
    )
    new_login = client.post(
        LOGIN_URL, json={"email": "ada@example.com", "password": "brand-new-password-1"}
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_reset_password_token_is_single_use(client: TestClient, db_session: Session) -> None:
    _register(client)
    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None

    from app.services.auth_service import _hash_reset_token

    raw_token = "a-single-use-token"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()

    first = client.post(
        RESET_PASSWORD_URL, json={"token": raw_token, "new_password": "first-new-password-1"}
    )
    second = client.post(
        RESET_PASSWORD_URL, json={"token": raw_token, "new_password": "second-new-password-1"}
    )
    assert first.status_code == 200
    assert second.status_code == 401


def test_reset_password_with_an_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.post(
        RESET_PASSWORD_URL, json={"token": "not-a-real-token", "new_password": "a-fine-password-1"}
    )
    assert response.status_code == 401


def test_reset_password_with_an_expired_token_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    _register(client)
    user = db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None

    from app.services.auth_service import _hash_reset_token

    raw_token = "an-expired-token"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    db_session.commit()

    response = client.post(
        RESET_PASSWORD_URL, json={"token": raw_token, "new_password": "a-fine-password-1"}
    )
    assert response.status_code == 401
