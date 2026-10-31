from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin
from app.models.types import JSONVariant

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.project import Project


class FileType(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class File(UUIDPKMixin, TimestampMixin, Base):
    """The dataset itself is never stored here — only where it lives in
    object storage (Phase 6) and what profiling learned about it."""

    __tablename__ = "files"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[FileType] = mapped_column(
        SAEnum(FileType, native_enum=False, length=10, validate_strings=True), nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Nullable: only known once profiling (Phase 6) has actually run —
    # in practice that happens synchronously during upload, so by the
    # time a File row is committed at all, these are always populated;
    # nullable reflects that fact isn't guaranteed by the schema itself.
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full profiling result (dataset-level + per-column detail, Phase 6
    # §5/§6) — stored so GET /profile doesn't need to re-fetch and
    # re-parse the file from storage on every request. row_count/
    # column_count stay as their own indexed/typed columns above rather
    # than only living inside this blob, since those two are exactly
    # the fields simple list/summary queries want without unpacking JSON.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    project: Mapped[Project] = relationship(back_populates="files")
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
