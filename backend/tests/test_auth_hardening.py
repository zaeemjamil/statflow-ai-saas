"""Brute-force throttling, real SMTP delivery and background dispatch."""

from __future__ import annotations

import logging
import smtplib
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import throttle
from app.core.config import Settings, get_settings
from app.core.throttle import AttemptLimiter
from app.services import email_service
from app.services.email_service import SmtpEmailProvider

AUTH = "/api/v1/auth"
PASSWORD = "correct-horse-1"


def _register(client: TestClient, email: str) -> None:
    assert (
        client.post(f"{AUTH}/register", json={"email": email, "password": PASSWORD}).status_code
        == 201
    )
    client.post(f"{AUTH}/logout")


def _login(client: TestClient, email: str, password: str) -> Any:
    return client.post(f"{AUTH}/login", json={"email": email, "password": password})


# --- limiter unit ---------------------------------------------------------


def test_limiter_blocks_at_the_limit_and_recovers_after_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    lim = AttemptLimiter()
    for _ in range(3):
        assert lim.retry_after("k", limit=3, window=60) == 0
        lim.record("k", window=60)
    assert lim.retry_after("k", limit=3, window=60) > 0
    assert lim.retry_after("other", limit=3, window=60) == 0
    clock[0] += 61
    assert lim.retry_after("k", limit=3, window=60) == 0


def test_limiter_memory_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(throttle, "_MAX_KEYS", 50)
    lim = AttemptLimiter()
    for i in range(500):
        lim.record(f"k{i}", window=3600)
    assert len(lim._events) <= 50


# --- login throttling -----------------------------------------------------


def test_repeated_wrong_passwords_lock_the_account_for_a_while(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    get_settings.cache_clear()
    _register(client, "victim@example.com")
    for _ in range(3):
        assert _login(client, "victim@example.com", "wrong-password-1").status_code == 401
    locked = _login(client, "victim@example.com", "wrong-password-1")
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "too_many_login_attempts"
    assert locked.json()["error"]["details"]["retry_after_seconds"] >= 1
    # even the CORRECT password is refused while locked (otherwise guessing could continue)
    assert _login(client, "victim@example.com", PASSWORD).status_code == 429


def test_the_lock_is_per_account_and_a_good_login_clears_the_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    get_settings.cache_clear()
    _register(client, "a@example.com")
    _register(client, "b@example.com")
    for _ in range(2):
        assert _login(client, "a@example.com", "nope-nope-nope").status_code == 401
    assert _login(client, "a@example.com", PASSWORD).status_code == 200  # resets a's count
    for _ in range(2):
        assert _login(client, "a@example.com", "nope-nope-nope").status_code == 401
    assert _login(client, "a@example.com", PASSWORD).status_code == 200
    for _ in range(3):
        _login(client, "b@example.com", "nope-nope-nope")
    assert _login(client, "b@example.com", PASSWORD).status_code == 429
    assert _login(client, "a@example.com", PASSWORD).status_code == 200  # a unaffected


def test_unknown_emails_are_throttled_the_same_way(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "2")
    get_settings.cache_clear()
    for _ in range(2):
        assert _login(client, "ghost@example.com", "whatever-pass-1").status_code == 401
    assert _login(client, "ghost@example.com", "whatever-pass-1").status_code == 429


# --- password-reset requests ------------------------------------------------


class RecordingProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None:
        self.sent.append((to_email, reset_token))


def test_reset_requests_are_rate_limited_silently_with_an_identical_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PASSWORD_RESET_MAX_PER_HOUR", "2")
    get_settings.cache_clear()
    provider = RecordingProvider()
    monkeypatch.setattr("app.api.v1.auth.get_email_provider", lambda _s: provider)
    _register(client, "mailbomb@example.com")
    bodies = []
    for _ in range(5):
        r = client.post(f"{AUTH}/forgot-password", json={"email": "mailbomb@example.com"})
        assert r.status_code == 200
        bodies.append(r.json())
    assert len({str(b) for b in bodies}) == 1  # throttling is not observable
    assert len(provider.sent) == 2  # but only 2 emails were actually dispatched


def test_the_email_is_sent_after_the_response_not_during_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class Slow:
        def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None:
            events.append("sent")

    monkeypatch.setattr("app.api.v1.auth.get_email_provider", lambda _s: Slow())
    _register(client, "later@example.com")
    r = client.post(f"{AUTH}/forgot-password", json={"email": "later@example.com"})
    assert r.status_code == 200
    assert events == ["sent"]  # TestClient runs background tasks after the response is built
    missing = client.post(f"{AUTH}/forgot-password", json={"email": "nobody@example.com"})
    assert missing.json() == r.json() and events == ["sent"]  # no email for unknown accounts


# --- SMTP provider ----------------------------------------------------------


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(
        self, host: str, port: int, timeout: float | None = None, context: Any = None
    ) -> None:
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[str] = []
        self.sent: list[Any] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: Any) -> None:
        self.calls.append("send")
        self.sent.append(message)


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    base = {
        "EMAIL_PROVIDER": "smtp",
        "SMTP_HOST": "mail.example.test",
        "FRONTEND_URL": "https://app.example.test",
    }
    for k, v in {**base, **env}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


def test_smtp_sends_a_link_to_the_frontend_with_starttls_and_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = _settings(monkeypatch, SMTP_USERNAME="user", SMTP_PASSWORD="pw")
    SmtpEmailProvider(settings).send_password_reset_email(
        to_email="u@example.com", reset_token="tok/+=?&x"
    )
    (smtp,) = FakeSMTP.instances
    assert (smtp.host, smtp.port) == (
        "mail.example.test",
        587,
    ) and smtp.timeout == settings.SMTP_TIMEOUT_SECONDS
    assert smtp.calls == ["starttls", "login:user", "send"]
    msg = smtp.sent[0]
    assert msg["To"] == "u@example.com" and msg["From"] == settings.EMAIL_FROM_ADDRESS
    body = msg.get_content()
    assert "https://app.example.test/reset-password?token=tok%2F%2B%3D%3F%26x" in body


def test_smtp_ssl_mode_uses_implicit_tls_and_skips_starttls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    settings = _settings(monkeypatch, SMTP_SSL="true", SMTP_PORT="465")
    SmtpEmailProvider(settings).send_password_reset_email(to_email="u@example.com", reset_token="t")
    assert FakeSMTP.instances[0].port == 465 and FakeSMTP.instances[0].calls == ["send"]


def test_smtp_failures_never_raise_and_never_log_the_token_or_address(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*a: object, **k: object) -> None:
        raise ConnectionRefusedError("down: secret-token-123 victim@example.com")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    caplog.set_level(logging.DEBUG)
    settings = _settings(monkeypatch)
    SmtpEmailProvider(settings).send_password_reset_email(
        to_email="victim@example.com", reset_token="secret-token-123"
    )
    assert "secret-token-123" not in caplog.text and "victim@example.com" not in caplog.text
    assert "could not be sent" in caplog.text


def test_provider_selection_and_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(email_service.get_email_provider(_settings(monkeypatch)), SmtpEmailProvider)
    monkeypatch.setenv("EMAIL_PROVIDER", "none")
    get_settings.cache_clear()
    assert isinstance(
        email_service.get_email_provider(get_settings()), email_service.LoggingEmailProvider
    )
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="SMTP_HOST"):
        get_settings()
