"""PDF report API (Phase 10). Same ownership rule as every project route."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_storage
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.report import ReportPublic
from app.services import project_service, report_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/projects", tags=["reports"])


@router.post(
    "/{project_id}/reports", response_model=ReportPublic, status_code=status.HTTP_201_CREATED
)
def create_report(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ReportPublic:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    report = report_service.generate_report(db, project, current_user, storage, settings)
    return ReportPublic.model_validate(report)


@router.get("/{project_id}/reports", response_model=list[ReportPublic])
def list_reports(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReportPublic]:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    return [ReportPublic.model_validate(r) for r in report_service.list_reports(db, project)]


@router.get("/{project_id}/reports/{report_id}/download")
def download_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> Response:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    report = report_service.get_report(db, project, report_id)
    data = report_service.read_report(report, storage)
    name = report.file_name or "report.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{project_id}/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> Response:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    report_service.delete_report(db, project, report_id, storage)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
