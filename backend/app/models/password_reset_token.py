from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class PasswordResetToken(UUIDPKMixin, CreatedAtMixin, Base):
    """A single-use, revocable password-reset token. Deliberately not a
    stateless JWT: a reset link needs to be invalidated the moment it's
    used (or superseded by a newer request) regardless of its expiry,
    which a signed-but-unstored token can't do. Only the token's hash is
    stored — like a password, the raw value is never persisted, so a DB
    leak alone can't be used to reset accounts."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()
