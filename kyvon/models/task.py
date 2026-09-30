from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kyvon.db import Base, UTCDateTime, utcnow

PRIORITIES = {1: "low", 2: "normal", 3: "high", 4: "urgent"}
RECURRENCES = ("daily", "weekly", "monthly", "yearly")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_status_due", "user_id", "status", "due_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | done
    priority: Mapped[int] = mapped_column(default=2)  # 1 low .. 4 urgent
    # Stored in UTC. Date-only tasks (due_has_time False) mean "that calendar day" in the
    # user's time zone; due_at is the start of that day.
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    due_has_time: Mapped[bool] = mapped_column(default=True)
    recurrence: Mapped[str | None] = mapped_column(String(8), default=None)
    recurrence_interval: Mapped[int] = mapped_column(default=1)
    source: Mapped[str] = mapped_column(String(16), default="user")  # user | assistant | automation
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
