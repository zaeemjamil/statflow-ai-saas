"""Public shapes for the AI analyst endpoints (Phase 9 Stage 2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

AI_DISCLAIMER = (
    "AI-generated explanation of the analysis on this page. It can be wrong or incomplete. "
    "Check every statement against the tables and charts, and do not treat it as proof of "
    "cause, significance or reliability."
)


class AIInsightPublic(BaseModel):
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    data_quality: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    # Closed-vocabulary caveat codes from the evidence (e.g. "small_sample").
    # Shown by the UI regardless of what the model wrote.
    evidence_warnings: list[str] = Field(default_factory=list)
    generated_at: datetime
    model: str
    prompt_version: str


class AIInsightsState(BaseModel):
    configured: bool
    eligible: bool
    reason_code: str | None = None
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    insight: AIInsightPublic | None = None
    # A stored explanation exists but the analysis changed since: it is withheld.
    has_outdated_insight: bool = False
    remaining_today: int
    disclaimer: str = AI_DISCLAIMER
