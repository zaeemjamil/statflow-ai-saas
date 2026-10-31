"""Public shape of a generated PDF report (Phase 10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    analysis_id: uuid.UUID
    file_name: str | None
    generated_at: datetime
