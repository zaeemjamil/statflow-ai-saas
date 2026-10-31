from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.subscription import Subscription
    from app.models.usage import UsageRecord


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Case normalization (e.g. lowercasing before insert/lookup) is a
    # Phase 5 (auth) application-layer concern, not a schema one.
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    projects: Mapped[list[Project]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[Subscription | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    usage_records: Mapped[list[UsageRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
