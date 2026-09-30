from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from kyvon.db import Base, UTCDateTime, utcnow


class PushSubscription(Base):
    """A device that can receive push notifications (Web Push now; APNs for the iOS app later)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="webpush")  # webpush | apns
    endpoint: Mapped[str] = mapped_column(Text, unique=True)  # push URL, or the APNs device token
    keys: Mapped[dict | None] = mapped_column(JSON, default=None)  # webpush: p256dh + auth
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
