"""Validation and display translation of AI output (Phase 9 Stage 2).

The model's reply is UNTRUSTED text. It is parsed strictly, sanitized, bounded,
and stored in aliased form (``Column_001``). Real column names are put back only
when it is READ, using the CURRENT local alias map, and only if the evidence
that produced the text is still the current evidence.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.aliases import AMBIGUOUS_ALIAS, ColumnAliasMap

SUMMARY_MAX = 1200
ITEM_MAX = 400
LIST_LIMITS = {"key_findings": 6, "data_quality": 4, "limitations": 5, "next_steps": 4}
MAX_RAW_OUTPUT_CHARS = 20_000
UNKNOWN_COLUMN = "[unknown column]"
DUPLICATE_COLUMN = "[a column whose name appears more than once]"
DISPLAY_NAME_MAX = 80

_ALIAS_RE = re.compile(r"\bColumn_(?:\d{3,}|ambiguous)\b")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class InvalidAIOutput(ValueError):
    """The provider answered, but not with a usable insight object."""


class AIInsightContent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=SUMMARY_MAX)
    key_findings: list[str] = Field(default_factory=list)
    data_quality: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


def clean_text(value: str, *, limit: int) -> str:
    """One line of plain text: NFC, no control/bidi characters, no links."""
    text = unicodedata.normalize("NFC", value)
    text = _CONTROL_RE.sub(" ", text)
    text = _URL_RE.sub("[link removed]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _clean_list(raw: Any, *, limit: int, max_items: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidAIOutput("A list field was not a list.")
    items = [clean_text(x, limit=limit) for x in raw if isinstance(x, str)]
    return [x for x in items if x][:max_items]


def _restrict_aliases(text: str, known: frozenset[str]) -> str:
    """Keep only aliases that exist in this evidence; a made-up one must not
    survive to be 'translated' into a real column later."""
    return _ALIAS_RE.sub(lambda m: m.group(0) if m.group(0) in known else UNKNOWN_COLUMN, text)


def parse_provider_output(raw: str, known_aliases: frozenset[str]) -> AIInsightContent:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_RAW_OUTPUT_CHARS:
        raise InvalidAIOutput("The reply was empty or too long.")
    text = raw.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InvalidAIOutput("The reply was not valid JSON.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        raise InvalidAIOutput("The reply did not contain a summary.")
    try:
        content = AIInsightContent(
            summary=clean_text(data["summary"], limit=SUMMARY_MAX),
            **{
                name: _clean_list(data.get(name), limit=ITEM_MAX, max_items=cap)
                for name, cap in LIST_LIMITS.items()
            },
        )
    except ValidationError as exc:
        raise InvalidAIOutput("The reply did not match the expected shape.") from exc
    allowed = known_aliases | {AMBIGUOUS_ALIAS}
    return AIInsightContent(
        summary=_restrict_aliases(content.summary, allowed),
        **{
            name: [_restrict_aliases(x, allowed) for x in getattr(content, name)]
            for name in LIST_LIMITS
        },
    )


def _display_name(original: str) -> str:
    return clean_text(original, limit=DISPLAY_NAME_MAX) or "(unnamed column)"


def translate_aliases(text: str, aliases: ColumnAliasMap) -> str:
    """Aliases -> real names, for DISPLAY ONLY (never sent anywhere)."""

    def swap(match: re.Match[str]) -> str:
        alias = match.group(0)
        try:
            original = aliases.original_for(alias)
        except KeyError:
            return DUPLICATE_COLUMN if alias == AMBIGUOUS_ALIAS else UNKNOWN_COLUMN
        if aliases.is_duplicated(original):
            return DUPLICATE_COLUMN
        return f"“{_display_name(original)}”"

    return _ALIAS_RE.sub(swap, text)


def translate_content(content: AIInsightContent, aliases: ColumnAliasMap) -> AIInsightContent:
    return AIInsightContent(
        summary=translate_aliases(content.summary, aliases),
        **{
            name: [translate_aliases(x, aliases) for x in getattr(content, name)]
            for name in LIST_LIMITS
        },
    )
