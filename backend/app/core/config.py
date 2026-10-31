"""
Application configuration, loaded from environment variables (and a local
.env file in development) via pydantic-settings.

Fields are grouped by when they're actually consumed:

  * Actively used: ENVIRONMENT, DATABASE_URL, FRONTEND_URL,
    API_V1_PREFIX, PROJECT_NAME (Phase 3); JWT_SECRET, JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES (Phase 5).

  * Later phases: everything else. These have permissive defaults so a
    checkout boots without needing secrets nothing reads yet. Each later
    phase should tighten validation as it starts actually using the
    field, rather than an earlier phase guessing at requirements it
    can't verify.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_JWT_SECRET = "changeme-not-a-real-secret-set-a-real-one"
_MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Phase 3: actively used ---------------------------------------
    PROJECT_NAME: str = "Zaimex API"
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str
    FRONTEND_URL: str = "http://localhost:3000"

    # --- Phase 5: actively used -----------------------------------------
    JWT_SECRET: str = _PLACEHOLDER_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # Cookie-based session (Phase 5 §"Authentication Strategy"). Secure
    # defaults to True — local dev over plain http://localhost must
    # explicitly set COOKIE_SECURE=false, rather than the default
    # quietly being insecure.
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # Password reset email (decision #3: provider is configurable so a
    # concrete provider can be added without touching call sites — see
    # app/services/email_service.py). Still not wired to a real vendor.
    # "none" logs only; "smtp" sends real mail through any SMTP server (provider-neutral).
    EMAIL_PROVIDER: str = "none"
    EMAIL_API_KEY: str | None = None
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = (
        True  # port 587 style; set false only for implicit-TLS (465) or local relays
    )
    SMTP_SSL: bool = False  # implicit TLS (port 465)
    SMTP_TIMEOUT_SECONDS: float = 15.0

    # Brute-force protection (in-memory, per server process).
    LOGIN_MAX_FAILURES: int = 8
    LOGIN_LOCKOUT_MINUTES: int = 15
    PASSWORD_RESET_MAX_PER_HOUR: int = 5
    EMAIL_FROM_ADDRESS: str = "noreply@zaimex.app"

    # --- Phase 6: actively used -----------------------------------------
    # Upload/dataset limits (V1 hardening). The effective byte limit for a
    # file is min(its per-type limit, MAX_UPLOAD_SIZE_MB): MAX_UPLOAD_SIZE_MB
    # is kept as the absolute ceiling (it predates the per-type limits, so
    # existing deployments/tests that set it keep working), the per-type
    # limits tighten it. XLSX is lower because it is a compressed format that
    # is ~10-100x slower to parse than CSV per MB (measured in the V1 audit).
    MAX_UPLOAD_SIZE_MB: int = 25
    MAX_CSV_UPLOAD_SIZE_MB: int = 25
    MAX_XLSX_UPLOAD_SIZE_MB: int = 10
    # Data rows (header excluded) and columns. Enforced while parsing.
    MAX_DATASET_ROWS: int = 100_000
    MAX_DATASET_COLUMNS: int = 100
    # An .xlsx is a zip: its on-disk size says little about how much XML the
    # parser must expand. Rejects archives that declare more than this.
    MAX_XLSX_UNCOMPRESSED_SIZE_MB: int = 250
    # Local filesystem storage backs dev/test (StorageService below).
    # STORAGE_ENDPOINT unset selects it; setting STORAGE_ENDPOINT is how a
    # future S3-compatible provider would be selected instead - see
    # app/services/storage_service.py's factory.
    LOCAL_STORAGE_PATH: str = "./var/storage"
    STORAGE_ENDPOINT: str | None = None
    STORAGE_ACCESS_KEY: str | None = None
    STORAGE_SECRET_KEY: str | None = None
    STORAGE_BUCKET: str | None = None

    # --- Phase 9: AI analyst (actively used) -----------------------------
    # The feature is OFF until OPENROUTER_API_KEY is set: every AI endpoint
    # then answers 503 `ai_not_configured` and nothing leaves the server.
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    AI_REQUEST_TIMEOUT_SECONDS: float = 45.0
    AI_MAX_OUTPUT_TOKENS: int = 1200
    # Minimum gap between two successful generations for the same analysis.
    AI_COOLDOWN_SECONDS: int = 15
    # Provider calls per user per UTC day (failed calls count: they cost too).
    AI_DAILY_LIMIT_PER_USER: int = 20

    @field_validator(
        "AI_REQUEST_TIMEOUT_SECONDS", "AI_MAX_OUTPUT_TOKENS", "AI_DAILY_LIMIT_PER_USER"
    )
    @classmethod
    def _ai_limits_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AI limits must be positive numbers.")
        return value

    @field_validator("AI_COOLDOWN_SECONDS")
    @classmethod
    def _ai_cooldown_must_not_be_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("AI_COOLDOWN_SECONDS must be zero or more.")
        return value

    @model_validator(mode="after")
    def _smtp_needs_a_host(self) -> Self:
        if self.EMAIL_PROVIDER == "smtp" and not (self.SMTP_HOST or "").strip():
            raise ValueError("EMAIL_PROVIDER=smtp requires SMTP_HOST.")
        if self.SMTP_SSL and self.SMTP_STARTTLS:
            self.SMTP_STARTTLS = False  # implicit TLS and STARTTLS are mutually exclusive
        return self

    @model_validator(mode="after")
    def _production_ai_endpoint_must_be_https(self) -> Self:
        # The API key and the (name-free) evidence travel to this URL.
        if self.ENVIRONMENT == "production" and not self.OPENROUTER_BASE_URL.startswith("https://"):
            raise ValueError("OPENROUTER_BASE_URL must use https:// in production.")
        return self

    @field_validator(
        "MAX_UPLOAD_SIZE_MB",
        "MAX_CSV_UPLOAD_SIZE_MB",
        "MAX_XLSX_UPLOAD_SIZE_MB",
        "MAX_DATASET_ROWS",
        "MAX_DATASET_COLUMNS",
        "MAX_XLSX_UNCOMPRESSED_SIZE_MB",
    )
    @classmethod
    def _limits_must_be_positive(cls, v: int) -> int:
        # A zero/negative limit would silently reject every upload (or, worse,
        # be read as "unlimited" by a future refactor) - fail at startup.
        if v < 1:
            raise ValueError("Upload/dataset limits must be positive integers.")
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def _database_url_must_be_postgres(cls, v: str) -> str:
        if not (v.startswith("postgresql://") or v.startswith("postgresql+psycopg2://")):
            raise ValueError("DATABASE_URL must be a postgresql:// (or postgresql+psycopg2://) URL")
        return v

    @model_validator(mode="after")
    def _samesite_none_requires_secure(self) -> Self:
        # Browsers reject SameSite=None cookies that aren't also Secure —
        # this misconfiguration should fail loudly at startup, not
        # silently produce cookies the browser drops.
        if self.COOKIE_SAMESITE == "none" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SAMESITE='none' requires COOKIE_SECURE=true (browser rule).")
        return self

    @model_validator(mode="after")
    def _production_must_not_use_a_weak_jwt_secret(self) -> Self:
        if not self.is_production:
            return self
        if self.JWT_SECRET == _PLACEHOLDER_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET is still the .env.example placeholder — set a real, "
                "random secret before starting in production."
            )
        if len(self.JWT_SECRET) < _MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {_MIN_JWT_SECRET_LENGTH} characters "
                "in production (it's the HMAC key signing every access token)."
            )
        return self

    @model_validator(mode="after")
    def _production_must_be_https_with_secure_cookies(self) -> Self:
        # A public deployment must never send the session cookie in clear text.
        if not self.is_production:
            return self
        if not self.COOKIE_SECURE:
            raise ValueError(
                "COOKIE_SECURE must be true in production (session cookies need HTTPS)."
            )
        if not self.FRONTEND_URL.startswith("https://"):
            raise ValueError("FRONTEND_URL must start with https:// in production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — env is read once per process."""
    return Settings()
