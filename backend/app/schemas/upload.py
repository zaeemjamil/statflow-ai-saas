"""Upload + profiling response schemas. Mirrors app/analytics/profiling.py's
return shape exactly - see that module's docstring."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models import FileType


class ColumnProfile(BaseModel):
    name: str
    classification: Literal["numeric", "categorical", "date"]
    pandas_dtype: str
    missing_count: int
    missing_percentage: float
    unique_count: int
    is_unique: bool
    min_value: float | None = None
    max_value: float | None = None
    # Stage 3 (all optional: profiles stored before Stage 3 lack them).
    likely_identifier: bool = False
    identifier_reason: str | None = None
    number_format: str | None = None
    number_format_examples: list[str] = []
    date_order_issue: str | None = None


class ImportNote(BaseModel):
    """A data-correctness finding shown to the user (Stage 3). Detect and
    explain only: the data itself is not changed by a note."""

    code: str
    severity: Literal["info", "warning"]
    message: str
    columns: list[str] = []
    details: dict[str, Any] = {}


class DatasetProfile(BaseModel):
    row_count: int
    column_count: int
    numeric_column_count: int
    categorical_column_count: int
    date_column_count: int
    total_missing_values: int
    duplicate_row_count: int
    columns: list[ColumnProfile]
    import_notes: list[ImportNote] = []


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    file_type: FileType
    size_bytes: int
    row_count: int | None
    column_count: int | None
    created_at: datetime


class UploadResponse(BaseModel):
    """What POST /projects/{id}/upload returns - file metadata plus the
    full profiling summary in one response, so the frontend's upload
    flow (Phase 2 journey step 4) doesn't need a second round trip."""

    file: FileInfo
    profile: DatasetProfile
