"""Audit trail of every tool call KYVON makes (or is asked to make)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from kyvon.db import Base, UTCDateTime, utcnow

# Lifecycle: pending_confirmation -> (confirmed) running -> succeeded | failed
#            pending_confirmation -> rejected | expired
#            (no confirmation needed) running -> succeeded | failed
#            an unknown tool, malformed or invalid arguments -> rejected/failed immediately
TOOL_RUN_STATUSES = (
    "pending_confirmation",
    "running",
    "succeeded",
    "failed",
    "rejected",
    "expired",
)


class ToolRun(Base):
    __tablename__ = "tool_runs"
    __table_args__ = (Index("ix_tool_runs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True, default=None
    )
    # Set when the call was made by an agent run (Phase 6).
    agent_run_id: Mapped[int | None] = mapped_column(index=True, default=None)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    risk: Mapped[str] = mapped_column(String(16), default="read")
    requires_confirmation: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[str] = mapped_column(String(500), default="")
    arguments: Mapped[dict | None] = mapped_column(JSON, default=None)
    raw_arguments: Mapped[str | None] = mapped_column(Text, default=None)  # only if malformed
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
