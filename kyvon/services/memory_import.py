"""One-time (and safely repeatable) import of the prototype's JSON memory file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Memory
from kyvon.services.memory_service import MemoryService


class MemoryImportError(Exception):
    """The memory file is unreadable or not in the prototype's format."""


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0


def _parse_date(value) -> datetime:
    """Prototype dates are naive local ISO strings; treat them as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return utcnow()
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def import_json_memories(session: Session, user_id: int, path: Path) -> ImportResult:
    """Import ``path`` for ``user_id``. The file is only read, never modified.

    Re-running is safe: an entry with the same text and timestamp is skipped,
    including entries that were later soft-deleted.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise MemoryImportError(f"Memory file not found: {path}") from error
    except (OSError, ValueError) as error:
        raise MemoryImportError(f"Could not read {path}: {error}") from error
    if not isinstance(data, list):
        raise MemoryImportError(f"{path} is not a JSON list of memories.")

    existing = {
        (m.content, m.created_at)
        for m in session.scalars(select(Memory).where(Memory.user_id == user_id))
    }

    service = MemoryService(session, user_id)
    result = ImportResult()
    for item in data:
        text = item.get("memory") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            result.skipped += 1
            continue
        created_at = _parse_date(item.get("date"))
        if (text, created_at) in existing:
            result.skipped += 1
            continue
        session.add(Memory(user_id=user_id, content=text, source="import", created_at=created_at))
        existing.add((text, created_at))
        result.imported += 1

    session.flush()
    service.enforce_limit()
    session.commit()
    return result
