"""AI analyst API (Phase 9 Stage 2). Same ownership rule as every project
route: a project that is not the caller's is a 404."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.api.deps import get_ai_provider, get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.ai import AIInsightsState
from app.services import ai_service, project_service

router = APIRouter(prefix="/projects", tags=["ai"])


@router.get("/{project_id}/ai-insights", response_model=AIInsightsState)
def get_ai_insights(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: AIProvider | None = Depends(get_ai_provider),
    settings: Settings = Depends(get_settings),
) -> AIInsightsState:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    return ai_service.get_state(
        db, project, current_user, settings, configured=provider is not None
    )


@router.post("/{project_id}/ai-insights", response_model=AIInsightsState)
def generate_ai_insights(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: AIProvider | None = Depends(get_ai_provider),
    settings: Settings = Depends(get_settings),
) -> AIInsightsState:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    return ai_service.generate(db, project, current_user, provider, settings)
