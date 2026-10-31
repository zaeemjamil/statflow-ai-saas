from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Statistic(UUIDPKMixin, CreatedAtMixin, Base):
    """One row per (column, metric) for an analysis's descriptive
    statistics — e.g. (Revenue, mean, 1245.30). Immutable once written,
    so no updated_at."""

    __tablename__ = "statistics"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "column_name", "metric", name="uq_statistics_analysis_column_metric"
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="statistics")
