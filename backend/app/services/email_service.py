"""
Abstracted email delivery — the requirement is explicit: "keep the
actual email delivery provider abstract/configurable. Do not hardwire
a specific provider yet." `EmailProvider` is the interface every future
provider (Resend, SES, Postmark, ...) implements; `LoggingEmailProvider`
is the only one that exists right now, and it never sends real email —
it logs, which is honest about what V1 actually does rather than
pretending a real provider is wired in.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote

from fastapi import BackgroundTasks

from app.core.config import Settings

logger = logging.getLogger("zaimex.email")


class EmailProvider(Protocol):
    def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None: ...


class LoggingEmailProvider:
    """V1's only implementation: logs that a reset was requested,
    without the token itself, instead of sending real email. The raw
    token is deliberately never logged - "do not log passwords/tokens/
    secrets" is unconditional, not "unless there's no email provider
    configured yet." (Tests that need a real token for the reset flow
    insert a PasswordResetToken row directly rather than reading it back
    out of here - see test_auth.py.) This is correct behavior for
    EMAIL_PROVIDER=none, not a placeholder standing in for missing
    functionality — there is no vendor to call yet, by design
    (decision #3)."""

    def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None:
        logger.info(
            "Password reset requested for %s (EMAIL_PROVIDER=none - no email provider "
            "configured, so no email was actually sent)",
            to_email,
        )


class SmtpEmailProvider:
    """Real delivery over plain SMTP, so any mail host works (no vendor is
    hardwired). The reset link points at the frontend. The token is never
    logged, and failures are logged WITHOUT the message so a mail outage can
    neither crash the request nor reveal whether an account exists."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _message(self, to_email: str, reset_token: str) -> EmailMessage:
        link = (
            f"{self._s.FRONTEND_URL.rstrip('/')}/reset-password?token={quote(reset_token, safe='')}"
        )
        msg = EmailMessage()
        msg["Subject"] = "Reset your StatFlow AI password"
        msg["From"] = self._s.EMAIL_FROM_ADDRESS
        msg["To"] = to_email
        msg.set_content(
            "Someone asked to reset the password for this account.\n\n"
            f"Open this link to choose a new password (valid for "
            f"{self._s.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):\n{link}\n\n"
            "If you did not ask for this, ignore this email; your password stays the same."
        )
        return msg

    def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None:
        s = self._s
        try:
            message = self._message(to_email, reset_token)
            context = ssl.create_default_context()
            host, port = str(s.SMTP_HOST), s.SMTP_PORT
            if s.SMTP_SSL:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    host, port, timeout=s.SMTP_TIMEOUT_SECONDS, context=context
                )
            else:
                client = smtplib.SMTP(host, port, timeout=s.SMTP_TIMEOUT_SECONDS)
            with client:
                if s.SMTP_STARTTLS and not s.SMTP_SSL:
                    client.starttls(context=context)
                if s.SMTP_USERNAME:
                    client.login(s.SMTP_USERNAME, s.SMTP_PASSWORD or "")
                client.send_message(message)
            logger.info("Password reset email handed to the SMTP server")
        except Exception as exc:
            logger.error("Password reset email could not be sent (%s)", type(exc).__name__)


class BackgroundEmailProvider:
    """Sends after the HTTP response, so a slow mail server neither delays the
    request nor makes 'account exists' observable through response time."""

    def __init__(self, inner: EmailProvider, tasks: BackgroundTasks) -> None:
        self._inner = inner
        self._tasks = tasks

    def send_password_reset_email(self, *, to_email: str, reset_token: str) -> None:
        self._tasks.add_task(
            self._inner.send_password_reset_email, to_email=to_email, reset_token=reset_token
        )


def get_email_provider(settings: Settings) -> EmailProvider:
    if settings.EMAIL_PROVIDER == "none":
        return LoggingEmailProvider()
    if settings.EMAIL_PROVIDER == "smtp":
        return SmtpEmailProvider(settings)
    raise NotImplementedError(
        f"EMAIL_PROVIDER={settings.EMAIL_PROVIDER!r} is not supported (use 'none' or 'smtp')."
    )
