"""Dashboard summary (Phase 8A). Every figure is a live query scoped to
the caller's own projects; nothing is hardcoded or cached."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Analysis, AnalysisStatus, Project, Report, User
from app.schemas.dashboard import DashboardSummary, RecentProject

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RECENT_PROJECT_LIMIT = 5


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummary:
    owned = Project.user_id == current_user.id

    total_projects = db.scalar(select(func.count(Project.id)).where(owned)) or 0

    # "Files analyzed" = distinct files with a completed analysis, not
    # files merely uploaded. Equal to completed projects in V1.
    files_analyzed = (
        db.scalar(
            select(func.count(distinct(Analysis.file_id)))
            .join(Project, Analysis.project_id == Project.id)
            .where(owned, Analysis.status == AnalysisStatus.COMPLETED)
        )
        or 0
    )

    # Real queries against tables Phases 9/10 will populate. They return
    # an honest 0 today because nothing writes those rows yet - no
    # special-casing needed when those phases land.
    reports_generated = (
        db.scalar(
            select(func.count(Report.id))
            .join(Project, Report.project_id == Project.id)
            .where(owned)
        )
        or 0
    )
    ai_insights_generated = (
        db.scalar(
            select(func.count(Analysis.id))
            .join(Project, Analysis.project_id == Project.id)
            .where(owned, Analysis.ai_insights.is_not(None))
        )
        or 0
    )

    recent = db.scalars(
        select(Project).where(owned).order_by(Project.updated_at.desc()).limit(RECENT_PROJECT_LIMIT)
    ).all()

    return DashboardSummary(
        total_projects=total_projects,
        files_analyzed=files_analyzed,
        reports_generated=reports_generated,
        ai_insights_generated=ai_insights_generated,
        recent_projects=[RecentProject.model_validate(p) for p in recent],
    )
