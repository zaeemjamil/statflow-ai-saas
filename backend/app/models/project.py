from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.file import File
    from app.models.report import Report
    from app.models.user import User


class ProjectStatus(StrEnum):
    CREATED = "created"
    UPLOADED = "uploaded"
    PROFILED = "profiled"
    CLEANING_PENDING = "cleaning_pending"
    CLEANING_COMPLETED = "cleaning_completed"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    # requirement: every project belongs to exactly one user
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=ProjectStatus.CREATED,
    )

    user: Mapped[User] = relationship(back_populates="projects")
    # One-to-many at the schema level even though V1 enforces exactly one
    # of each at the application layer (Phase 2 decision #1) — this is
    # the "extensible without redesigning" requirement in practice.
    files: Mapped[list[File]] = relationship(back_populates="project", cascade="all, delete-orphan")
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
