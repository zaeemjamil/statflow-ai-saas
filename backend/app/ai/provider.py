"""Provider boundary for the AI analyst (Phase 9 Stage 2).

``OpenRouterProvider`` is the only code that talks to the network for AI. It
sends exactly the chat messages it is given (built by ``prompt.build_messages``
from ``EvidencePacket.canonical_json()``). Safety properties, each tested:
  * the API key goes only in the Authorization header, never in a body, log
    line or error message;
  * redirects are not followed (a redirect could carry the key elsewhere);
  * the response is size-capped and its body is never echoed into errors/logs
    (a provider may echo the prompt back);
  * every failure becomes a ``ProviderError`` with a fixed, safe message.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 1_000_000


class ProviderError(Exception):
    """A failed provider call. ``message`` is safe to show to the user."""

    code = "ai_provider_error"
    message = "The AI service could not complete the request. Please try again later."

    def __init__(self) -> None:
        super().__init__(self.message)


class ProviderTimeout(ProviderError):
    code = "ai_provider_timeout"
    message = "The AI service took too long to answer. Please try again."


class ProviderBusy(ProviderError):
    code = "ai_provider_busy"
    message = "The AI service is busy right now. Please try again in a minute."


class ProviderRejected(ProviderError):
    code = "ai_provider_rejected"
    message = (
        "The AI service rejected this server's credentials. "
        "The administrator must check the API key."
    )


@dataclass(frozen=True)
class ProviderResult:
    text: str
    model: str


class AIProvider(Protocol):
    model: str

    def generate(self, messages: list[dict[str, str]]) -> ProviderResult: ...


class OpenRouterProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_output_tokens: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout_seconds
        self._max_tokens = max_output_tokens
        self._transport = transport

    def __repr__(self) -> str:  # never print the key
        return f"<OpenRouterProvider model={self.model!r}>"

    def generate(self, messages: list[dict[str, str]]) -> ProviderResult:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "StatFlow AI",
        }
        raw = bytearray()
        try:
            with httpx.Client(
                timeout=self._timeout, follow_redirects=False, transport=self._transport
            ) as client:
                with client.stream("POST", self._url, headers=headers, json=body) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise ProviderRejected()
                    if status == 429:
                        raise ProviderBusy()
                    if status != 200:
                        logger.warning("AI provider answered HTTP %s", status)
                        raise ProviderError()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise ProviderError()
        except httpx.TimeoutException as exc:
            raise ProviderTimeout() from exc
        except httpx.HTTPError as exc:
            logger.warning("AI provider request failed: %s", type(exc).__name__)
            raise ProviderError() from exc

        try:
            data = json.loads(bytes(raw))
            message = data["choices"][0]["message"]["content"]
            returned_model = data.get("model")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError() from exc
        if not isinstance(message, str):
            raise ProviderError()
        model = returned_model if isinstance(returned_model, str) and returned_model else self.model
        return ProviderResult(text=message, model=model[:100])


def build_provider(settings: Settings) -> AIProvider | None:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        return None
    return OpenRouterProvider(
        api_key=key,
        model=settings.OPENROUTER_MODEL,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout_seconds=settings.AI_REQUEST_TIMEOUT_SECONDS,
        max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
    )
