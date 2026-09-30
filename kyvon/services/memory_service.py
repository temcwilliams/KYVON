"""Long-term memory: create, edit, delete, list and retrieve. Always scoped to one user.

Deleting is a soft delete (``deleted_at``), so removals are recoverable from the database
and never silently lose data. What reaches the prompt is chosen by a ``MemoryRetriever``,
not by "the last N".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Memory
from kyvon.services.errors import NotFoundError
from kyvon.services.memory_retrieval import LexicalRetriever, MemoryRetriever, Scored
from kyvon.services.memory_rules import (
    DEFAULT_CATEGORY,
    content_hash,
    parse_memory_shortcut,
    parse_recall_request,
    validate_category,
    validate_importance,
    validate_memory_text,
)

__all__ = [
    "MemoryService",
    "SaveResult",
    "parse_memory_shortcut",
    "parse_recall_request",
    "serialize_memory",
]

MAX_MEMORIES = 100  # default cap; the app passes Settings.memory_max
NO_MEMORIES_TEXT = "No saved memories."


@dataclass
class SaveResult:
    memory: Memory
    created: bool  # False when an identical memory already existed


def serialize_memory(m: Memory, *, score: float | None = None) -> dict:
    data = {
        "id": m.id,
        "memory": m.content,
        "category": m.category or DEFAULT_CATEGORY,
        "importance": m.importance,
        "source": m.source,
        "date": m.created_at.isoformat(),
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        "last_used_at": m.last_used_at.isoformat() if m.last_used_at else None,
        "use_count": m.use_count,
    }
    if score is not None:
        data["score"] = round(score, 3)
    return data


class MemoryService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        now: Callable[[], datetime] = utcnow,
        max_memories: int = MAX_MEMORIES,
        retriever: MemoryRetriever | None = None,
        retrieval_k: int = 8,
    ):
        self._session = session
        self._user_id = user_id
        self._now = now
        self._max = max_memories
        self._retriever = retriever or LexicalRetriever()
        self._k = retrieval_k

    # ------------------------------------------------------------ queries

    def _live(self):
        return (
            select(Memory)
            .where(Memory.user_id == self._user_id, Memory.deleted_at.is_(None))
            .order_by(Memory.created_at, Memory.id)
        )

    def _live_rows(self) -> list[Memory]:
        return list(self._session.scalars(self._live()))

    def get(self, memory_id: int) -> Memory:
        memory = self._session.scalar(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.user_id == self._user_id,
                Memory.deleted_at.is_(None),
            )
        )
        if memory is None:
            raise NotFoundError("Memory not found.")
        return memory

    def all(self) -> list[dict]:
        return [serialize_memory(m) for m in self._live_rows()]

    def list(
        self, *, category: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[Memory], int]:
        query = self._live()
        if category:
            query = query.where(Memory.category == validate_category(category))
        total = self._session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        rows = list(
            self._session.scalars(
                query.order_by(None)
                .order_by(Memory.created_at.desc(), Memory.id.desc())
                .limit(max(1, min(limit, 500)))
                .offset(max(offset, 0))
            )
        )
        return rows, total

    def __len__(self) -> int:
        return self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.user_id == self._user_id, Memory.deleted_at.is_(None))
        )

    # ------------------------------------------------------------ changes

    def add(
        self,
        text: str,
        *,
        category: str | None = None,
        importance: int | None = None,
        source: str = "user",
        created_at: datetime | None = None,
    ) -> SaveResult:
        """Save a memory. An identical one that already exists is returned, not duplicated."""
        cleaned = validate_memory_text(text)
        category = validate_category(category)
        importance = validate_importance(importance)

        digest = content_hash(cleaned)
        existing = self._session.scalar(
            select(Memory).where(
                Memory.user_id == self._user_id,
                Memory.content_hash == digest,
                Memory.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return SaveResult(existing, created=False)

        memory = Memory(
            user_id=self._user_id,
            content=cleaned,
            category=category,
            importance=importance,
            source=source,
            created_at=created_at or self._now(),
        )
        self._session.add(memory)
        self._session.flush()
        self.enforce_limit()
        self._session.commit()
        return SaveResult(memory, created=True)

    def update(
        self,
        memory_id: int,
        *,
        text: str | None = None,
        category: str | None = None,
        importance: int | None = None,
    ) -> Memory:
        memory = self.get(memory_id)
        if text is not None:
            cleaned = validate_memory_text(text)
            digest = content_hash(cleaned)
            clash = self._session.scalar(
                select(Memory.id).where(
                    Memory.user_id == self._user_id,
                    Memory.content_hash == digest,
                    Memory.deleted_at.is_(None),
                    Memory.id != memory.id,
                )
            )
            if clash is not None:
                from kyvon.services.errors import ConflictError

                raise ConflictError("Another memory already says exactly that.")
            memory.content = cleaned
        if category is not None:
            memory.category = validate_category(category)
        if importance is not None:
            memory.importance = validate_importance(importance)
        memory.updated_at = self._now()
        self._session.commit()
        return memory

    def delete(self, memory_id: int) -> None:
        memory = self.get(memory_id)
        memory.deleted_at = self._now()
        self._session.commit()

    def enforce_limit(self) -> None:
        """Keep at most ``max_memories``; the oldest, least important ones are retired first."""
        live = self._live_rows()
        overflow = len(live) - self._max
        if overflow <= 0:
            return
        for old in sorted(live, key=lambda m: (m.importance, m.created_at, m.id))[:overflow]:
            old.deleted_at = self._now()

    # ------------------------------------------------------------ retrieval

    def search(self, query: str, limit: int | None = None) -> list[Scored]:
        return self._retriever.rank(query, self._live_rows(), limit or self._k, now=self._now())

    def retrieve(self, query: str, limit: int | None = None) -> list[Scored]:
        """Relevant memories for ``query``; marks them as used."""
        hits = self.search(query, limit)
        if hits:
            now = self._now()
            for hit in hits:
                hit.memory.last_used_at = now
                hit.memory.use_count = (hit.memory.use_count or 0) + 1
            self._session.commit()
        return hits

    def retrieve_text(self, query: str) -> str:
        """The memory block for the system prompt: only what is relevant to ``query``."""
        hits = self.retrieve(query)
        return "\n".join(f"- {h.memory.content}" for h in hits)

    def recall_text(self, topic: str | None) -> str:
        """A readable answer to "what do you remember (about X)?"."""
        if topic:
            hits = [h.memory for h in self.search(topic, 20)]
        else:
            hits = self._live_rows()[-20:][::-1]
        if not hits:
            return (
                f"I don't have anything saved about {topic}."
                if topic
                else "I don't have any saved memories yet."
            )
        header = f"Here is what I remember about {topic}:" if topic else "Here is what I remember:"
        return header + "\n" + "\n".join(f"• {m.content}" for m in hits)

    def prompt_text(self) -> str:
        """The newest memories, unranked (kept for callers that have no query)."""
        rows = self._live_rows()[-20:]
        return "\n".join(f"- {m.content}" for m in rows) if rows else NO_MEMORIES_TEXT
