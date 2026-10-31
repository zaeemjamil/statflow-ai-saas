from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class SubscriptionPlan(StrEnum):
    FREE = "free"
    PRO = "pro"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELED = "canceled"


class Subscription(UUIDPKMixin, TimestampMixin, Base):
    """One row per user (enforced by the unique constraint on user_id),
    representing their current plan — not a billing/invoice history.
    No payment provider integration yet (out of Phase 4 scope); `plan`
    and `status` are just enough for the rest of the app to check
    entitlements against."""

    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        SAEnum(SubscriptionPlan, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=SubscriptionPlan.FREE,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )

    user: Mapped[User] = relationship(back_populates="subscription")
