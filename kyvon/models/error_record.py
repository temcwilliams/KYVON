from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kyvon.db import Base, UTCDateTime, utcnow


class ErrorRecord(Base):
    """An unexpected failure worth looking at. Text is redacted before it is stored."""

    __tablename__ = "error_records"
    __table_args__ = (Index("ix_error_records_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str | None] = mapped_column(String(64), default=None)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    resolution: Mapped[str | None] = mapped_column(String(500), default=None)  # repair note
