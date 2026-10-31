"""Dashboard summary schema - every count here is a real query result
(Phase 8A: "do NOT return hardcoded/demo values"). `reports_generated`
and `ai_insights_generated` are honestly 0 until Phases 9/10 exist;
there is no mechanism to populate them yet, so a nonzero value here
would have to be fabricated."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ProjectStatus


class RecentProject(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: ProjectStatus
    updated_at: datetime


class DashboardSummary(BaseModel):
    total_projects: int
    files_analyzed: int
    reports_generated: int
    ai_insights_generated: int
    recent_projects: list[RecentProject]
