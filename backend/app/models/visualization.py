from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin
from app.models.types import JSONVariant

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Visualization(UUIDPKMixin, CreatedAtMixin, Base):
    """One row per recommended chart for an analysis. `config` carries
    the chart spec (x/y fields, data) the frontend's Recharts components
    render — never a rendered image, so Phase 10 can reuse it for the
    PDF's charts too (Phase 2 "connects to Phase 1 backend")."""

    __tablename__ = "visualizations"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Not a DB enum: Phase 7 owns the exact set of chart-type strings
    # (Phase 1's scatter/line/bar/histogram rules), so adding one is a
    # code change in analytics/visualization.py, not a migration.
    chart_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="visualizations")
