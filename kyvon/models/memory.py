from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from kyvon.db import Base, UTCDateTime, utcnow


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64), default=None)
    source: Mapped[str] = mapped_column(String(16), default="user")  # user | import
    importance: Mapped[int] = mapped_column(default=3)  # 1 (minor) .. 5 (always relevant)
    use_count: Mapped[int] = mapped_column(default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


@event.listens_for(Memory, "before_insert")
@event.listens_for(Memory, "before_update")
def _refresh_content_hash(_mapper, _connection, memory: Memory) -> None:
    # Imported here: the rules module imports nothing from models, keeping this cycle-free.
    from kyvon.services.memory_rules import content_hash

    memory.content_hash = content_hash(memory.content)
