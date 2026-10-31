"""
Persistence-aware analysis flows for a project (Phase 8A).

`analysis_service.run_analysis` (Phase 7) stays a pure, DB-free
orchestrator. This module is the thin layer that loads a project's
stored file, calls that engine, and persists the outcome into the
Phase 4 `analyses` / `statistics` / `visualizations` tables, so every
read endpoint (dashboard, statistics, correlations, outliers, charts,
and later the AI and PDF phases) serves the *same persisted result*
rather than recomputing anything.

Design notes:

* The cleaned DataFrame is never stored. Cleaning is deterministic, so
  the persisted cleaning *config* is enough to reproduce it; later
  calls (`/analyze`, `/regression`) re-apply it to the stored source
  file. Re-parsing a <=20MB file per request is cheap at V1 scale and
  avoids a cache with cross-request consistency problems.
* Re-cleaning invalidates downstream results (statistics, correlations,
  outliers, regression, charts), because they were computed from a
  differently-cleaned dataset. Serving them next to the new cleaning
  report would present numbers that don't match it.
* V1 = one file and one analysis per project. The queries below pick
  "the" file/analysis; the schema itself already allows more.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import profiling, visualization
from app.analytics.cleaning import CleaningConfig, clean_dataset
from app.analytics.regression import run_regression
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models import (
    Analysis,
    AnalysisStatus,
    File,
    Project,
    ProjectStatus,
    Statistic,
    Visualization,
)
from app.schemas.analysis import (
    AnalysisPublic,
    ChartRecommendation,
    ColumnStatistics,
    CorrelationResult,
    DescriptiveStatistics,
    OutlierResult,
    RegressionResult,
    VisualizationResult,
)
from app.services import analysis_service, file_service
from app.services.storage_service import StorageService

logger = logging.getLogger("zaimex.analysis")

ALL_STAGES = analysis_service.STAGES


# --- loading ----------------------------------------------------------


def _require_file(project: Project) -> File:
    if not project.files:
        raise ConflictException(
            "Upload a dataset to this project before analysing it.",
            error_code="no_file_uploaded",
        )
    # V1: one file per project. Newest wins if that ever changes.
    return max(project.files, key=lambda f: f.created_at)


def _get_analysis(db: Session, project: Project) -> Analysis | None:
    return db.scalars(
        select(Analysis)
        .where(Analysis.project_id == project.id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    ).first()


def get_analysis_or_404(db: Session, project: Project) -> Analysis:
    analysis = _get_analysis(db, project)
    if analysis is None:
        raise NotFoundException(
            "No analysis exists for this project yet.", error_code="analysis_not_found"
        )
    return analysis


def _load_dataframe(file: File, storage: StorageService) -> pd.DataFrame:
    try:
        content = storage.get_file(storage_key=file.storage_key)
    except Exception as exc:
        # Never echo the storage key or backend error to the client.
        logger.error("Stored file missing for file %s", file.id)
        raise NotFoundException(
            "The uploaded file could not be found.", error_code="file_unavailable"
        ) from exc
    # Files uploaded before Stage 3 are re-read with the missing-value policy
    # their stored profile was built with, so the analysed data and the
    # profile shown to the user agree (no migration; see RECOVERY.md).
    return file_service.parse_dataset(
        content,
        file.file_type,
        legacy_na_policy=file_service.is_legacy_upload(file.profile),
    )


def _classifications(profile: dict[str, Any]) -> dict[str, str]:
    return {column["name"]: column["classification"] for column in profile["columns"]}


def _stored_cleaning_config(analysis: Analysis | None) -> CleaningConfig:
    if analysis is None or not analysis.cleaning:
        return CleaningConfig()
    config = analysis.cleaning.get("report", {}).get("config", {})
    return CleaningConfig(
        numeric_strategy=config.get("numeric_strategy", "median"),
        categorical_strategy=config.get("categorical_strategy", "mode"),
        duplicate_strategy=config.get("duplicate_strategy", "keep"),
    )


def _file_profile(file: File, df: pd.DataFrame) -> dict[str, Any]:
    # Files uploaded before the profile column existed have none; fall
    # back to profiling the parsed data rather than failing.
    return dict(file.profile) if file.profile else profiling.profile_dataset(df)


def _get_or_create_analysis(db: Session, project: Project, file: File) -> Analysis:
    analysis = _get_analysis(db, project)
    if analysis is None:
        analysis = Analysis(project_id=project.id, file_id=file.id, status=AnalysisStatus.PENDING)
        db.add(analysis)
        db.flush()
    return analysis


def _clear_derived_results(db: Session, analysis: Analysis) -> None:
    db.execute(delete(Statistic).where(Statistic.analysis_id == analysis.id))
    db.execute(delete(Visualization).where(Visualization.analysis_id == analysis.id))
    db.expire(analysis, ["statistics", "visualizations"])
    analysis.correlations = None
    analysis.outliers = None
    analysis.regression = None
    analysis.ai_insights = None  # an explanation of old results must not outlive them


def _mark_failed(db: Session, project: Project, analysis: Analysis | None, message: str) -> None:
    # Both rows were committed before the work started, so they survive
    # the rollback and can simply be updated.
    db.rollback()
    project.status = ProjectStatus.FAILED
    if analysis is not None:
        analysis.status = AnalysisStatus.FAILED
        analysis.error_message = message
        analysis.current_stage = None
    db.commit()


# --- flows ------------------------------------------------------------


def clean_project(
    db: Session, project: Project, config: CleaningConfig, storage: StorageService
) -> Analysis:
    """Run ONLY the cleaning step and persist its report. Statistics and
    the rest are computed by `analyze_project`."""
    file = _require_file(project)
    analysis = _get_or_create_analysis(db, project, file)
    previous_status = project.status
    project.status = ProjectStatus.CLEANING_PENDING
    db.commit()

    try:
        df = _load_dataframe(file, storage)
        profile = _file_profile(file, df)
        cleaned_df, report = clean_dataset(df, _classifications(profile), config)
        cleaned_profile = profiling.profile_dataset(cleaned_df)
    except (ValidationException, NotFoundException):
        # A problem with the request or the stored file, not a pipeline
        # failure: put the project back where it was so the user can retry.
        db.rollback()
        project.status = previous_status
        db.commit()
        raise
    except Exception:
        logger.exception("Cleaning failed for project %s", project.id)
        _mark_failed(db, project, analysis, "Cleaning could not be completed for this dataset.")
        raise

    _clear_derived_results(db, analysis)
    analysis.cleaning = {"report": report, "cleaned_profile": cleaned_profile}
    analysis.stages = {"profiling": "completed", "cleaning": "completed"}
    analysis.status = AnalysisStatus.PENDING
    analysis.error_message = None
    analysis.current_stage = None
    analysis.completed_at = None
    project.status = ProjectStatus.CLEANING_COMPLETED
    db.commit()
    db.refresh(analysis)
    return analysis


def analyze_project(db: Session, project: Project, storage: StorageService) -> Analysis:
    """Run the full Phase 7 pipeline using the stored cleaning config
    (or the defaults if /clean was never called) and persist every result.
    Re-running replaces the previous statistics/charts rather than
    duplicating them."""
    file = _require_file(project)
    analysis = _get_or_create_analysis(db, project, file)
    config = _stored_cleaning_config(analysis)
    previous_regression_stage = (analysis.stages or {}).get("regression")

    project.status = ProjectStatus.ANALYZING
    analysis.status = AnalysisStatus.RUNNING
    analysis.current_stage = "statistics"
    analysis.started_at = datetime.now(UTC)
    analysis.error_message = None
    db.commit()

    try:
        df = _load_dataframe(file, storage)
        profile = _file_profile(file, df)
        result = analysis_service.run_analysis(df, cleaning_config=config, profile=profile)
    except (ValidationException, NotFoundException) as exc:
        _mark_failed(db, project, analysis, exc.message)
        raise
    except Exception:
        logger.exception("Analysis failed for project %s", project.id)
        _mark_failed(db, project, analysis, "The analysis could not be completed for this dataset.")
        raise

    db.execute(delete(Statistic).where(Statistic.analysis_id == analysis.id))
    db.execute(delete(Visualization).where(Visualization.analysis_id == analysis.id))

    for column in result["statistics"].get("columns", []):
        for metric, value in column.items():
            if metric == "column" or value is None:
                continue
            db.add(
                Statistic(
                    analysis_id=analysis.id,
                    column_name=column["column"],
                    metric=metric,
                    value=float(value),
                )
            )
    for position, chart in enumerate(result["visualizations"].get("charts", [])):
        db.add(
            Visualization(
                analysis_id=analysis.id,
                chart_type=chart["chart_type"],
                title=chart["title"],
                config={"display_order": position, **chart},
            )
        )
    db.expire(analysis, ["statistics", "visualizations"])

    stages = dict(result["stages"])
    # Regression is requested separately; keep its state if it already ran.
    stages["regression"] = previous_regression_stage or "skipped"

    analysis.cleaning = {
        "report": result["cleaning"],
        "cleaned_profile": result["cleaned_profile"],
    }
    analysis.correlations = result["correlations"]
    analysis.outliers = result["outliers"]
    analysis.stages = stages
    analysis.status = AnalysisStatus.COMPLETED
    analysis.current_stage = None
    analysis.completed_at = datetime.now(UTC)
    project.status = ProjectStatus.COMPLETED
    db.commit()
    db.refresh(analysis)
    return analysis


def run_project_regression(
    db: Session,
    project: Project,
    target: str,
    predictors: list[str],
    storage: StorageService,
) -> Analysis:
    """Fit the requested regression on the cleaned data and persist it.

    A rejected configuration raises (422 with a specific error code) and
    leaves any previously-saved regression untouched - a typo in a new
    request must not wipe out a good earlier result."""
    analysis = get_analysis_or_404(db, project)
    if analysis.status != AnalysisStatus.COMPLETED:
        raise ConflictException(
            "Run the analysis before fitting a regression.",
            error_code="analysis_not_completed",
        )
    file = _require_file(project)
    df = _load_dataframe(file, storage)
    profile = _file_profile(file, df)
    classifications = _classifications(profile)
    cleaned_df, _ = clean_dataset(df, classifications, _stored_cleaning_config(analysis))

    result = run_regression(cleaned_df, classifications, target, predictors)

    analysis.regression = result
    analysis.stages = {**(analysis.stages or {}), "regression": "completed"}
    db.commit()
    db.refresh(analysis)
    return analysis


# --- reading ----------------------------------------------------------


def _stage(analysis: Analysis, name: str) -> str:
    return str((analysis.stages or {}).get(name, "pending"))


def require_stage_completed(analysis: Analysis, name: str) -> None:
    if _stage(analysis, name) != "completed":
        raise ConflictException(
            f"The {name} step has not completed for this project yet.",
            error_code="analysis_not_completed",
        )


def build_statistics(analysis: Analysis, profile: dict[str, Any] | None) -> DescriptiveStatistics:
    by_column: dict[str, dict[str, float]] = {}
    for row in analysis.statistics:
        by_column.setdefault(row.column_name, {})[row.metric] = row.value

    # Dataset column order, not row order: rows have no inherent order.
    order = [c["name"] for c in (profile or {}).get("columns", [])]
    names = sorted(by_column, key=lambda n: order.index(n) if n in order else len(order))

    columns = [
        ColumnStatistics(
            column=name,
            count=int(by_column[name].get("count", 0)),
            missing_count=int(by_column[name].get("missing_count", 0)),
            mean=by_column[name].get("mean"),
            median=by_column[name].get("median"),
            std=by_column[name].get("std"),
            min=by_column[name].get("min"),
            q1=by_column[name].get("q1"),
            q3=by_column[name].get("q3"),
            max=by_column[name].get("max"),
            iqr=by_column[name].get("iqr"),
        )
        for name in names
    ]
    skipped = [n for n in order if n not in by_column]
    return DescriptiveStatistics(
        columns=columns, numeric_column_count=len(columns), skipped_columns=skipped
    )


def build_visualizations(analysis: Analysis) -> VisualizationResult:
    rows = sorted(analysis.visualizations, key=lambda v: v.config.get("display_order", 0))
    # bound_chart_payload shrinks per-row data of analyses stored before
    # sampling existed (no-op for newly stored ones), so old projects don't
    # keep returning one point per row.
    charts = [
        ChartRecommendation.model_validate(visualization.bound_chart_payload(row.config))
        for row in rows
    ]
    if not charts:
        return VisualizationResult(available=False, reason="no_chartable_column_combinations_found")
    return VisualizationResult(available=True, charts=charts, chart_count=len(charts))


def build_correlations(analysis: Analysis) -> CorrelationResult | None:
    data = analysis.correlations
    if not data or "error_code" in data:
        return None
    return CorrelationResult.model_validate(data)


def build_outliers(analysis: Analysis) -> OutlierResult | None:
    data = analysis.outliers
    if not data or "error_code" in data:
        return None
    return OutlierResult.model_validate(data)


def to_public(analysis: Analysis) -> AnalysisPublic:
    """Assemble the public representation from persisted state only."""
    cleaning_blob = analysis.cleaning or {}
    file = analysis.file
    stages = {name: _stage(analysis, name) for name in ALL_STAGES}

    return AnalysisPublic.model_validate(
        {
            "id": analysis.id,
            "project_id": analysis.project_id,
            "file_id": analysis.file_id,
            "status": analysis.status.value,
            "current_stage": analysis.current_stage,
            "stages": stages,
            "profile": file.profile,
            "cleaned_profile": cleaning_blob.get("cleaned_profile"),
            "cleaning": cleaning_blob.get("report"),
            "statistics": (
                build_statistics(analysis, file.profile)
                if stages["statistics"] == "completed"
                else None
            ),
            "correlations": build_correlations(analysis),
            "outliers": build_outliers(analysis),
            "regression": (
                RegressionResult.model_validate(analysis.regression)
                if analysis.regression
                else None
            ),
            "visualizations": (
                build_visualizations(analysis) if stages["visualizations"] == "completed" else None
            ),
            "error_message": analysis.error_message,
            "started_at": analysis.started_at,
            "completed_at": analysis.completed_at,
            "created_at": analysis.created_at,
            "updated_at": analysis.updated_at,
        }
    )
