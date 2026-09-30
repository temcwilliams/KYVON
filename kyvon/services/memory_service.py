"""Memory: shortcut parsing and the database-backed, user-scoped memory service.

Rules carried over from the prototype: only the newest 100 memories are kept and
only the newest 20 go into the prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Memory

MAX_MEMORIES = 100
PROMPT_MEMORIES = 20
NO_MEMORIES_TEXT = "No saved memories."

# Checked in order. Note that "remember " (below) matches before "remember that ",
# so "remember that X" is stored as "that X". Preserved from the prototype.
_REMEMBER_PREFIX = "remember "
_MEMORY_PHRASES = ("remember that ", "don't forget that ", "keep in mind that ")


def parse_memory_shortcut(message: str) -> str | None:
    """Return the text to remember if ``message`` is a memory shortcut, else None.

    ``message`` is expected to be already stripped, as the chat route does.
    """
    lower = message.lower()

    if lower.startswith(_REMEMBER_PREFIX):
        text = message[len(_REMEMBER_PREFIX) :].strip()
        if text:
            return text

    for phrase in _MEMORY_PHRASES:
        if lower.startswith(phrase):
            text = message[len(phrase) :].strip()
            if text:
                return text

    return None


class MemoryService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        now: Callable[[], datetime] = utcnow,
        max_memories: int = MAX_MEMORIES,
    ):
        self._session = session
        self._user_id = user_id
        self._now = now
        self._max = max_memories

    def _live(self):
        return (
            select(Memory)
            .where(Memory.user_id == self._user_id, Memory.deleted_at.is_(None))
            .order_by(Memory.created_at, Memory.id)
        )

    def add(self, text: str, *, source: str = "user", created_at: datetime | None = None) -> Memory:
        memory = Memory(
            user_id=self._user_id,
            content=text,
            source=source,
            created_at=created_at or self._now(),
        )
        self._session.add(memory)
        self._session.flush()
        self.enforce_limit()
        self._session.commit()
        return memory

    def enforce_limit(self) -> None:
        live = list(self._session.scalars(self._live()))
        for old in live[: max(len(live) - self._max, 0)]:
            old.deleted_at = self._now()

    def all(self) -> list[dict]:
        return [
            {"id": m.id, "date": m.created_at.isoformat(), "memory": m.content}
            for m in self._session.scalars(self._live())
        ]

    def __len__(self) -> int:
        return self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.user_id == self._user_id, Memory.deleted_at.is_(None))
        )

    def retrieve_text(self, query: str) -> str:
        """Memory block for a prompt. (Relevance-based retrieval arrives with Phase 3.)"""
        return self.prompt_text()

    def prompt_text(self) -> str:
        memories = list(self._session.scalars(self._live()))
        if not memories:
            return NO_MEMORIES_TEXT
        return "\n".join(f"- {m.content}" for m in memories[-PROMPT_MEMORIES:])
