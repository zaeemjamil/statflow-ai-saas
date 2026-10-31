"""expand project status enum

Revision ID: 64ede1957f2f
Revises: 2385df85301e
Create Date: 2026-10-04 09:16:07.828809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64ede1957f2f'
down_revision: Union[str, Sequence[str], None] = '2385df85301e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No DDL change, confirmed against the real schema before writing
    this: `projects.status` is a plain VARCHAR(20) with no CHECK
    constraint (the `native_enum=False` SAEnum column never had one -
    enforcement has only ever been at the SQLAlchemy/ORM level via
    `validate_strings=True`, not the database). The new enum values
    (profiled/cleaning_pending/cleaning_completed/analyzing) all fit
    within 20 characters, so expanding `ProjectStatus` in
    app/models/project.py needed no corresponding schema change - this
    revision exists only to mark that point in migration history."""


def downgrade() -> None:
    """No DDL to reverse - see upgrade()."""
