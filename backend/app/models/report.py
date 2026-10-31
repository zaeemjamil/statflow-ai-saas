from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.project import Project


class Report(UUIDPKMixin, Base):
    """One row per generated PDF. Immutable once written - regenerating
    a report creates a new row (Phase 1: "download reports", plural),
    so history of past reports is free, not a design decision to make
    later. No CreatedAtMixin here: the field is named `generated_at`
    (matching the Phase 2 spec) rather than the mixin's `created_at`."""

    __tablename__ = "reports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Traceability: exactly which analysis's results this PDF's numbers
    # came from - requirement: "PDF report values must come from the
    # same analysis results shown in the dashboard."
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="reports")
    analysis: Mapped[Analysis] = relationship(back_populates="reports")
