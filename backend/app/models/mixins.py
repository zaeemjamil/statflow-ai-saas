"""
Shared column mixins so every model gets the same PK/timestamp behavior
without repeating column definitions nine times.

`sqlalchemy.Uuid` (not `postgresql.UUID`) is deliberate: it's the
dialect-agnostic type added in SQLAlchemy 2.0 — genuine `uuid` on
Postgres in production, a portable representation on SQLite in tests
(Phase 4's "no real Postgres required for unit tests" requirement)
without any dialect-branching code of our own.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    """Adds a UUID primary key, generated client-side."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    """For append-only/immutable-after-insert tables (statistics,
    visualizations, reports) — no updated_at, because these rows are
    never updated once written."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """For mutable tables (users, projects, files, analyses,
    subscriptions, usage) — adds updated_at on top of created_at."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
