from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from kyvon.db import Base, UTCDateTime, utcnow


class Subscription(Base):
    """A person's paid-plan state, kept in step with Stripe by signed webhooks."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(64), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(24), default="incomplete")
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False)
    last_event_at: Mapped[int] = mapped_column(default=0)  # Stripe event time: ignore older events
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BillingEvent(Base):
    """Every Stripe event id we have processed, so a replayed webhook changes nothing."""

    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(String(80), unique=True)
    type: Mapped[str] = mapped_column(String(80))
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
