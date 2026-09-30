"""Persistent memory backed by the prototype's JSON file format.

Behavior is intentionally identical to the legacy app.py memory code:

* entries are ``{"date": <ISO timestamp>, "memory": <text>}``
* only the most recent 100 are kept
* the prompt sees only the most recent 20
* an unreadable or non-list file loads as empty
* the file is written with ``indent=4``
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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


class MemoryStore:
    def __init__(self, path: Path, *, now: Callable[[], datetime] = datetime.now):
        self.path = Path(path)
        self._now = now
        self._lock = threading.Lock()
        self._memories: list[dict] = self._read()

    def _read(self) -> list[dict]:
        try:
            if not self.path.exists():
                return []
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._memories, f, indent=4)

    def all(self) -> list[dict]:
        return list(self._memories)

    def __len__(self) -> int:
        return len(self._memories)

    def add(self, text: str) -> None:
        with self._lock:
            self._memories.append({"date": self._now().isoformat(), "memory": text})
            self._memories = self._memories[-MAX_MEMORIES:]
            self._write()

    def prompt_text(self) -> str:
        """Memory block injected into the system prompt (last 20, newest last)."""
        if not self._memories:
            return NO_MEMORIES_TEXT
        return "\n".join(
            f"- {item.get('memory', '')}" for item in self._memories[-PROMPT_MEMORIES:]
        )

    def reload(self) -> list[dict]:
        """Re-read the file (used by diagnostics) without replacing in-memory state."""
        return self._read()


# ---------------------------------------------------------------------------
# Database-backed memory (user-scoped). Same rules as MemoryStore: the newest
# 100 are kept, and the newest 20 go into the prompt. Overflow is soft-deleted.
# ---------------------------------------------------------------------------


class MemoryService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        now: Callable[[], datetime] = utcnow,
    ):
        self._session = session
        self._user_id = user_id
        self._now = now

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
        for old in live[:-MAX_MEMORIES]:
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

    def prompt_text(self) -> str:
        memories = list(self._session.scalars(self._live()))
        if not memories:
            return NO_MEMORIES_TEXT
        return "\n".join(f"- {m.content}" for m in memories[-PROMPT_MEMORIES:])
