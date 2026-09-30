from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from kyvon.db import Base, UTCDateTime, utcnow

KINDS = ("reminder", "prompt")


class Automation(Base):
    """A persisted scheduled action: what to do, when, and how it has been going."""

    __tablename__ = "automations"
    __table_args__ = (Index("ix_automations_due", "enabled", "next_run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # reminder | prompt
    payload: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # {"text"} or {"prompt", "conversation_id"?}
    schedule: Mapped[dict] = mapped_column(JSON)  # validated spec, see automation/schedules.py
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    enabled: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(16), default="user")  # user | assistant
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_status: Mapped[str | None] = mapped_column(String(16), default=None)
    run_count: Mapped[int] = mapped_column(default=0)
    failure_count: Mapped[int] = mapped_column(default=0)  # consecutive failures
    disabled_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    automation_id: Mapped[int] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    triggered_by: Mapped[str] = mapped_column(
        String(16), default="schedule"
    )  # schedule|manual|retry
    status: Mapped[str] = mapped_column(
        String(16), default="running"
    )  # running|succeeded|failed|skipped
    result: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class Notification(Base):
    """Something KYVON wants the user to see (a reminder, an automation result, an approval)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="automation")
    automation_id: Mapped[int | None] = mapped_column(
        ForeignKey("automations.id", ondelete="SET NULL"), default=None
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
