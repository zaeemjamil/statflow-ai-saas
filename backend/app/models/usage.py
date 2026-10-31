from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class UsageRecord(UUIDPKMixin, TimestampMixin, Base):
    """One row per (user, metric, period) - e.g. (user, 'analyses_run',
    2026-09-01) -> count. Table name is `usage` per the approved entity
    list; class is `UsageRecord` since a bare `Usage` reads oddly as a
    Python class name for one row."""

    __tablename__ = "usage"
    __table_args__ = (
        UniqueConstraint("user_id", "metric", "period_start", name="uq_usage_user_metric_period"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship(back_populates="usage_records")
