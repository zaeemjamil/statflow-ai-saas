"""
Minimal logging setup. Without this, Python's root logger defaults to
WARNING, which silently swallows every `logger.info(...)` call in the
app - including `LoggingEmailProvider`'s, whose entire purpose is being
visible in development. Confirmed empirically: a live forgot-password
request produced no log line at all before this existed.
"""

import logging

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,  # re-configure cleanly even if something already called basicConfig
    )
