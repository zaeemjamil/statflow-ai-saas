"""Project CRUD request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ProjectUpdate(BaseModel):
    # V1 only supports renaming (Phase 1: "rename projects") - status is
    # never client-settable, it reflects pipeline state the server owns.
    name: str = Field(..., min_length=1, max_length=255)


class ProjectPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
