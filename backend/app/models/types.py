"""
JSONVariant: plain JSON everywhere, genuine JSONB on Postgres.

Using this instead of `postgresql.JSONB` directly is what lets the same
model definitions run against SQLite in tests (Phase 4's requirement)
while still getting real JSONB — binary storage, indexable — in
production. SQLAlchemy picks the right one per-connection automatically;
no dialect branching in application code.
"""

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine

JSONVariant: TypeEngine[Any] = JSON().with_variant(JSONB(), "postgresql")
