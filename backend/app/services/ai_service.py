"""AI analyst service (Phase 9 Stage 2).

Flow: stored analysis -> public view -> eligibility -> evidence packet (aliased,
name-free) -> prompt built from ``packet.canonical_json()`` -> provider ->
strict validation -> stored in ``analyses.ai_insights`` (still aliased).
Real column names are restored only when READING, with the CURRENT alias map,
and only while the evidence fingerprint still matches. Evidence and model
output are never logged.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.eligibility import EvidenceNotEligible, check_eligibility
from app.ai.evidence import EvidenceBuild, build_evidence
from app.ai.output import (
    LIST_LIMITS,
    AIInsightContent,
    InvalidAIOutput,
    parse_provider_output,
    translate_content,
)
from app.ai.prompt import PROMPT_VERSION, build_messages
from app.ai.provider import AIProvider, ProviderError
from app.core.config import Settings
from app.core.exceptions import (
    BadGatewayException,
    ServiceUnavailableException,
    TooManyRequestsException,
)
from app.models import Analysis, Project, UsageRecord, User
from app.schemas.ai import AIInsightPublic, AIInsightsState
from app.services import project_analysis_service as analysis_svc

logger = logging.getLogger(__name__)

USAGE_METRIC = "ai_insights"
RECORD_VERSION = 1


def _today() -> date:
    return datetime.now(UTC).date()


def _usage_row(db: Session, user: User, *, create: bool) -> UsageRecord | None:
    stmt = select(UsageRecord).where(
        UsageRecord.user_id == user.id,
        UsageRecord.metric == USAGE_METRIC,
        UsageRecord.period_start == _today(),
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None and create:
        row = UsageRecord(user_id=user.id, metric=USAGE_METRIC, period_start=_today(), count=0)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:  # another request created it first
            db.rollback()
            row = db.execute(stmt).scalar_one()
    return row


def _remaining_today(db: Session, user: User, settings: Settings) -> int:
    row = _usage_row(db, user, create=False)
    used = row.count if row is not None else 0
    return max(0, settings.AI_DAILY_LIMIT_PER_USER - used)


def _record_content(record: dict[str, Any]) -> AIInsightContent:
    stored = record["insight"]
    return AIInsightContent(
        summary=stored["summary"], **{name: list(stored.get(name, [])) for name in LIST_LIMITS}
    )


def _public_insight(record: dict[str, Any], build: EvidenceBuild) -> AIInsightPublic:
    content = translate_content(_record_content(record), build.aliases)
    return AIInsightPublic(
        summary=content.summary,
        key_findings=content.key_findings,
        data_quality=content.data_quality,
        limitations=content.limitations,
        next_steps=content.next_steps,
        evidence_warnings=list(record.get("evidence_warnings", [])),
        generated_at=datetime.fromisoformat(record["generated_at"]),
        model=str(record.get("model", "")),
        prompt_version=str(record.get("prompt_version", "")),
    )


def get_state(
    db: Session, project: Project, user: User, settings: Settings, *, configured: bool
) -> AIInsightsState:
    analysis = analysis_svc.get_analysis_or_404(db, project)
    public = analysis_svc.to_public(analysis)
    verdict = check_eligibility(public)
    remaining = _remaining_today(db, user, settings)
    record = analysis.ai_insights if isinstance(analysis.ai_insights, dict) else None

    if not verdict.eligible:
        return AIInsightsState(
            configured=configured,
            eligible=False,
            reason_code=verdict.reason_code,
            message=verdict.message,
            has_outdated_insight=record is not None,
            remaining_today=remaining,
        )

    build = build_evidence(public)
    insight: AIInsightPublic | None = None
    outdated = False
    if record is not None:
        if record.get("evidence_fingerprint") == build.packet.fingerprint:
            insight = _public_insight(record, build)
        else:
            outdated = True
    return AIInsightsState(
        configured=configured,
        eligible=True,
        warnings=list(verdict.warnings),
        insight=insight,
        has_outdated_insight=outdated,
        remaining_today=remaining,
    )


def generate(
    db: Session,
    project: Project,
    user: User,
    provider: AIProvider | None,
    settings: Settings,
) -> AIInsightsState:
    if provider is None:
        raise ServiceUnavailableException(
            "AI insights are not set up on this server yet.", error_code="ai_not_configured"
        )
    analysis: Analysis = analysis_svc.get_analysis_or_404(db, project)
    public = analysis_svc.to_public(analysis)
    verdict = check_eligibility(public)
    if not verdict.eligible:
        raise EvidenceNotEligible(verdict)
    build = build_evidence(public)
    packet = build.packet

    existing = analysis.ai_insights if isinstance(analysis.ai_insights, dict) else None
    if existing and settings.AI_COOLDOWN_SECONDS > 0:
        try:
            age = (
                datetime.now(UTC) - datetime.fromisoformat(existing["generated_at"])
            ).total_seconds()
        except (KeyError, ValueError, TypeError):
            age = float("inf")
        if 0 <= age < settings.AI_COOLDOWN_SECONDS:
            wait = int(settings.AI_COOLDOWN_SECONDS - age) + 1
            raise TooManyRequestsException(
                f"Please wait {wait} seconds before generating again.",
                error_code="ai_rate_limited",
                details={"retry_after_seconds": wait},
            )

    usage = _usage_row(db, user, create=True)
    assert usage is not None
    if usage.count >= settings.AI_DAILY_LIMIT_PER_USER:
        db.rollback()
        raise TooManyRequestsException(
            "You have reached today's limit for AI explanations. Try again tomorrow.",
            error_code="ai_daily_limit",
            details={"daily_limit": settings.AI_DAILY_LIMIT_PER_USER},
        )
    usage.count += 1
    db.commit()  # counted before the call: failed calls cost money too

    messages = build_messages(packet)  # re-verifies the packet; sends canonical_json() only
    try:
        result = provider.generate(messages)
    except ProviderError as exc:
        logger.warning("AI generation failed analysis=%s code=%s", analysis.id, exc.code)
        raise BadGatewayException(exc.message, error_code=exc.code) from exc

    try:
        content = parse_provider_output(result.text, frozenset(build.aliases.aliases()))
    except InvalidAIOutput as exc:
        logger.warning("AI output rejected analysis=%s", analysis.id)
        raise BadGatewayException(
            "The AI service returned an answer that could not be used. Please try again.",
            error_code="ai_invalid_response",
        ) from exc

    analysis.ai_insights = {
        "version": RECORD_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "model": result.model,
        "prompt_version": PROMPT_VERSION,
        "evidence_fingerprint": packet.fingerprint,
        "evidence_size_bytes": packet.size_bytes,
        "evidence_warnings": list(verdict.warnings),
        "insight": content.model_dump(),
    }
    db.commit()
    logger.info(
        "AI insight stored analysis=%s fingerprint=%s model=%s",
        analysis.id,
        packet.fingerprint,
        result.model,
    )
    return get_state(db, project, user, settings, configured=True)
