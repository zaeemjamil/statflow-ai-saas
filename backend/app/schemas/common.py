"""Schemas shared across every API version and endpoint. Domain schemas
(auth, project, analysis, report) are added in the phases that need them
(Phase 5+) rather than stubbed here — an unused schema is dead weight,
not foundation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code, e.g. 'not_found'.")
    message: str = Field(..., description="Human-readable, safe-to-display message.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional machine-readable context, e.g. {'limit': 100000}. "
        "Omitted from the response when not applicable.",
    )


class ErrorResponse(BaseModel):
    """The shape of every non-2xx JSON response the API returns."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    environment: str = Field(..., examples=["development"])
    version: str = Field(..., examples=["0.1.0"])
