from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin
from app.models.types import JSONVariant

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.project import Project
    from app.models.report import Report
    from app.models.statistic import Statistic
    from app.models.visualization import Visualization


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Analysis(UUIDPKMixin, TimestampMixin, Base):
    """One row per analysis run. V1 creates exactly one per project
    (Phase 2 decision #1) — enforced in the service layer, not here, so
    multiple re-runs later need no schema change.

    Correlations/outliers/regression/AI results live in JSONB rather
    than their own tables, since only `statistics` and `visualizations`
    are in the approved entity list — same data, no extra tables.
    """

    __tablename__ = "analyses"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        SAEnum(AnalysisStatus, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )
    # One of: cleaning / statistics / outliers / regression / ai_insights
    # / report — the Phase 2 §2 staged-progress UI labels. Nullable:
    # only meaningful while status == RUNNING.
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    cleaning: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    correlations: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    outliers: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    regression: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    ai_insights: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    # Per-stage pipeline state for this persisted run, e.g.
    # {"cleaning": "completed", "statistics": "failed"}. Persisted rather
    # than inferred so the API reports what genuinely ran (Phase 8A: "do
    # not fake progress") even when a stage degraded gracefully.
    stages: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="analyses")
    file: Mapped[File] = relationship(back_populates="analyses")
    statistics: Mapped[list[Statistic]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    visualizations: Mapped[list[Visualization]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
