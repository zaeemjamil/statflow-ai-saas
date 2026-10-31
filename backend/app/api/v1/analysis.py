"""
Analysis API (Phase 8A). Every route takes `get_current_user` and
resolves the project through `get_owned_project`, so a project that
isn't the caller's is a 404 exactly like one that doesn't exist.

All reads serve the *persisted* result of the last analysis run; none
of them recompute anything, so the dashboard, statistics, correlations,
outliers, regression and charts can never disagree with each other
(and Phases 9/10 will quote the same stored numbers).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.cleaning import CleaningConfig
from app.api.deps import get_current_user, get_storage
from app.core.database import get_db
from app.core.exceptions import ConflictException
from app.models import Project, User
from app.schemas.analysis import (
    AnalysisPublic,
    CleanRequest,
    CorrelationResult,
    DescriptiveStatistics,
    OutlierResult,
    RegressionRequest,
    VisualizationResult,
)
from app.services import project_analysis_service as svc
from app.services import project_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/projects", tags=["analysis"])


def _owned(project_id: uuid.UUID, db: Session, user: User) -> Project:
    return project_service.get_owned_project(db, project_id=project_id, user=user)


@router.post("/{project_id}/clean", response_model=AnalysisPublic)
def clean(
    project_id: uuid.UUID,
    body: CleanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> AnalysisPublic:
    project = _owned(project_id, db, current_user)
    config = CleaningConfig(
        numeric_strategy=body.numeric_strategy,
        categorical_strategy=body.categorical_strategy,
        duplicate_strategy=body.duplicate_strategy,
    )
    return svc.to_public(svc.clean_project(db, project, config, storage))


@router.post("/{project_id}/analyze", response_model=AnalysisPublic)
def analyze(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> AnalysisPublic:
    project = _owned(project_id, db, current_user)
    return svc.to_public(svc.analyze_project(db, project, storage))


@router.get("/{project_id}/analysis", response_model=AnalysisPublic)
def get_analysis(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysisPublic:
    project = _owned(project_id, db, current_user)
    return svc.to_public(svc.get_analysis_or_404(db, project))


@router.get("/{project_id}/statistics", response_model=DescriptiveStatistics)
def get_statistics(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DescriptiveStatistics:
    analysis = svc.get_analysis_or_404(db, _owned(project_id, db, current_user))
    svc.require_stage_completed(analysis, "statistics")
    return svc.build_statistics(analysis, analysis.file.profile)


@router.get("/{project_id}/correlations", response_model=CorrelationResult)
def get_correlations(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CorrelationResult:
    analysis = svc.get_analysis_or_404(db, _owned(project_id, db, current_user))
    svc.require_stage_completed(analysis, "correlations")
    result = svc.build_correlations(analysis)
    if result is None:
        raise ConflictException(
            "Correlations could not be computed for this dataset.",
            error_code="analysis_stage_failed",
        )
    return result


@router.get("/{project_id}/outliers", response_model=OutlierResult)
def get_outliers(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OutlierResult:
    analysis = svc.get_analysis_or_404(db, _owned(project_id, db, current_user))
    svc.require_stage_completed(analysis, "outliers")
    result = svc.build_outliers(analysis)
    if result is None:
        raise ConflictException(
            "Outliers could not be computed for this dataset.",
            error_code="analysis_stage_failed",
        )
    return result


@router.post("/{project_id}/regression", response_model=AnalysisPublic)
def regression(
    project_id: uuid.UUID,
    body: RegressionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> AnalysisPublic:
    project = _owned(project_id, db, current_user)
    analysis = svc.run_project_regression(db, project, body.target, body.predictors, storage)
    return svc.to_public(analysis)


@router.get("/{project_id}/charts", response_model=VisualizationResult)
def get_charts(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VisualizationResult:
    analysis = svc.get_analysis_or_404(db, _owned(project_id, db, current_user))
    svc.require_stage_completed(analysis, "visualizations")
    return svc.build_visualizations(analysis)
