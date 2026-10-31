"""Phase 10 report service: render a PDF from the stored analysis (the same
``AnalysisPublic`` the dashboard shows), keep it in storage, and record it.
Reports are immutable; regenerating creates a new row. Ownership is enforced by
the caller resolving the project with ``get_owned_project``."""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    TooManyRequestsException,
)
from app.models import AnalysisStatus, Project, Report, User
from app.services import ai_service
from app.services import project_analysis_service as analysis_svc
from app.services.report_pdf import build_report_pdf
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

MAX_REPORTS_PER_PROJECT = 20
COOLDOWN_SECONDS = 5
MAX_PDF_BYTES = 20 * 1024 * 1024


def _slug(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-")[:40] or "report"


def list_reports(db: Session, project: Project) -> list[Report]:
    stmt = (
        select(Report)
        .where(Report.project_id == project.id)
        .order_by(Report.generated_at.desc(), Report.id)
    )
    return list(db.execute(stmt).scalars())


def get_report(db: Session, project: Project, report_id: uuid.UUID) -> Report:
    report = db.get(Report, report_id)
    if report is None or report.project_id != project.id:
        raise NotFoundException("Report not found.")
    return report


def generate_report(
    db: Session, project: Project, user: User, storage: StorageService, settings: Settings
) -> Report:
    analysis = analysis_svc.get_analysis_or_404(db, project)
    if analysis.status != AnalysisStatus.COMPLETED:
        raise ConflictException(
            "Run the analysis first, then create the report.", error_code="analysis_not_completed"
        )
    analysis_svc.require_stage_completed(analysis, "statistics")

    latest = list_reports(db, project)[:1]
    if latest:
        age = (
            datetime.now(UTC)
            - latest[0].generated_at.replace(tzinfo=latest[0].generated_at.tzinfo or UTC)
        ).total_seconds()
        if 0 <= age < COOLDOWN_SECONDS:
            raise TooManyRequestsException(
                "A report was just created. Please wait a few seconds.",
                error_code="report_rate_limited",
                details={"retry_after_seconds": int(COOLDOWN_SECONDS - age) + 1},
            )

    public = analysis_svc.to_public(analysis)
    ai = ai_service.get_state(db, project, user, settings, configured=False).insight
    now = datetime.now(UTC)
    pdf = build_report_pdf(
        project_name=project.name,
        file_name=analysis.file.original_filename,
        analysis=public,
        ai=ai,
        generated_at=now,
    )
    if len(pdf) > MAX_PDF_BYTES:
        raise ConflictException("The report is too large to create.", error_code="report_too_large")

    key = f"reports/{project.id}/{uuid.uuid4().hex}.pdf"
    storage.save_file(storage_key=key, content=pdf)
    try:
        report = Report(
            project_id=project.id,
            analysis_id=analysis.id,
            storage_key=key,
            file_name=f"{_slug(project.name)}-report-{now:%Y%m%d-%H%M}.pdf",
            generated_at=now,
        )
        db.add(report)
        db.commit()
    except Exception:
        db.rollback()
        _delete_object(storage, key)
        raise
    db.refresh(report)

    for old in list_reports(db, project)[MAX_REPORTS_PER_PROJECT:]:
        old_key = old.storage_key
        db.delete(old)
        db.commit()
        _delete_object(storage, old_key)
    logger.info("report created project=%s report=%s bytes=%d", project.id, report.id, len(pdf))
    return report


def read_report(report: Report, storage: StorageService) -> bytes:
    try:
        return storage.get_file(storage_key=report.storage_key)
    except (FileNotFoundError, OSError) as exc:
        raise NotFoundException(
            "The report file is no longer available. Create a new report.",
            error_code="report_file_unavailable",
        ) from exc


def delete_report(
    db: Session, project: Project, report_id: uuid.UUID, storage: StorageService
) -> None:
    report = get_report(db, project, report_id)
    key = report.storage_key
    db.delete(report)
    db.commit()
    _delete_object(storage, key)


def _delete_object(storage: StorageService, key: str) -> None:
    try:
        storage.delete_file(storage_key=key)
    except Exception:  # an orphaned file is better than a failed request
        logger.warning("Failed to delete report object %r", key)
