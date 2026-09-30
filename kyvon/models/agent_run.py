from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from kyvon.db import Base, UTCDateTime, utcnow

AGENT_RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "timeout")
FINISHED_STATUSES = ("succeeded", "failed", "cancelled", "timeout")


class AgentRun(Base):
    """One execution of a specialised agent, with its limits, cost and trace."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    parent_run_id: Mapped[int | None] = mapped_column(default=None)
    agent: Mapped[str] = mapped_column(String(32))
    goal: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="chat")  # chat | api | automation
    status: Mapped[str] = mapped_column(String(16), default="queued")
    depth: Mapped[int] = mapped_column(default=0)
    result: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    steps: Mapped[int] = mapped_column(default=0)  # model calls
    tool_calls: Mapped[int] = mapped_column(default=0)
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    model: Mapped[str | None] = mapped_column(String(100), default=None)
    pending_run_ids: Mapped[list | None] = mapped_column(JSON, default=None)  # awaiting approval
    trace: Mapped[list | None] = mapped_column(JSON, default=None)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
