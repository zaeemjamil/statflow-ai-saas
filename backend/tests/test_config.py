import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_required_fields_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py's autouse fixture clears the get_settings cache before
    # and after every test, so no manual cache_clear() is needed here.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    settings = get_settings()
    assert settings.DATABASE_URL == "postgresql://u:p@localhost:5432/db"


def test_environment_defaults_to_development(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py sets ENVIRONMENT=test in os.environ for the whole
    # session (env vars always win over field defaults), so the class
    # default is only observable with that var explicitly absent here.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(DATABASE_URL="postgresql://u:p@localhost:5432/db", _env_file=None)
    assert settings.ENVIRONMENT == "development"
    assert settings.is_production is False


def test_production_environment_is_detected() -> None:
    settings = Settings(
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
        ENVIRONMENT="production",
        JWT_SECRET="a" * 32,
        EMAIL_PROVIDER="resend",
        COOKIE_SECURE=True,
        FRONTEND_URL="https://app.example.com",
    )
    assert settings.is_production is True


def _prod(**over: object) -> Settings:
    base: dict[str, object] = {
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "ENVIRONMENT": "production",
        "JWT_SECRET": "a" * 48,
        "COOKIE_SECURE": True,
        "FRONTEND_URL": "https://app.example.com",
    }
    return Settings(_env_file=None, **{**base, **over})  # type: ignore[arg-type]


def test_production_requires_secure_cookies_and_an_https_site_url() -> None:
    assert _prod().is_production is True
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        _prod(COOKIE_SECURE=False)
    with pytest.raises(ValidationError, match="https://"):
        _prod(FRONTEND_URL="http://app.example.com")
    # outside production, local http development still works
    assert Settings(
        _env_file=None, DATABASE_URL="postgresql://u:p@localhost:5432/db", ENVIRONMENT="development"
    ).COOKIE_SECURE in (False, True)


def test_production_ai_endpoint_must_be_https_and_ai_limits_must_be_positive() -> None:
    assert _prod(OPENROUTER_BASE_URL="https://llm.example.com/v1").OPENROUTER_BASE_URL.startswith(
        "https://"
    )
    with pytest.raises(ValidationError, match="OPENROUTER_BASE_URL"):
        _prod(OPENROUTER_BASE_URL="http://llm.example.com/v1")
    for field in ("AI_DAILY_LIMIT_PER_USER", "AI_REQUEST_TIMEOUT_SECONDS", "AI_MAX_OUTPUT_TOKENS"):
        with pytest.raises(ValidationError):
            _prod(**{field: 0})
    with pytest.raises(ValidationError):
        _prod(AI_COOLDOWN_SECONDS=-1)


def test_smtp_provider_needs_a_host_and_unknown_providers_are_still_rejected_loudly() -> None:
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        _prod(EMAIL_PROVIDER="smtp")
    assert (
        _prod(EMAIL_PROVIDER="smtp", SMTP_HOST="smtp.example.com").SMTP_HOST == "smtp.example.com"
    )
    from app.services.email_service import get_email_provider

    with pytest.raises(NotImplementedError):
        get_email_provider(_prod(EMAIL_PROVIDER="resend"))


def test_non_postgres_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(DATABASE_URL="mysql://u:p@localhost:3306/db")


def test_missing_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py sets DATABASE_URL in os.environ for the whole test
    # session, so it has to be explicitly cleared here to actually test
    # the "missing" case rather than reading conftest's value.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
