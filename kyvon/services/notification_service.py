"""In-app notifications (the inbox). Push delivery, when configured, is layered on top."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Notification
from kyvon.services.errors import NotFoundError
from kyvon.utils.redact import redact

log = logging.getLogger("kyvon.notifications")
MAX_TITLE = 200
MAX_BODY = 2000


def serialize_notification(n: Notification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "source": n.source,
        "automation_id": n.automation_id,
        "conversation_id": n.conversation_id,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


class NotificationService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        now: Callable[[], datetime] = utcnow,
        push: Any = None,
    ):
        self._s = session
        self._user_id = user_id
        self._now = now
        self._push = push

    def create(
        self,
        title: str,
        body: str = "",
        *,
        source: str = "automation",
        automation_id: int | None = None,
        conversation_id: int | None = None,
    ) -> Notification:
        note = Notification(
            user_id=self._user_id,
            title=redact(title)[:MAX_TITLE],
            body=redact(body)[:MAX_BODY],
            source=source,
            automation_id=automation_id,
            conversation_id=conversation_id,
            created_at=self._now(),
        )
        self._s.add(note)
        self._s.commit()
        if self._push is not None:
            try:  # push is best effort; the inbox entry is the record
                self._push.send(self._s, self._user_id, note.title, note.body, note.id)
            except Exception:
                log.exception("push delivery failed")
        return note

    def list(self, *, unread_only: bool = False, limit: int = 50) -> list[Notification]:
        query = select(Notification).where(Notification.user_id == self._user_id)
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        return list(
            self._s.scalars(query.order_by(Notification.id.desc()).limit(max(1, min(limit, 200))))
        )

    def unread_count(self) -> int:
        return self._s.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == self._user_id, Notification.read_at.is_(None))
        )

    def _get(self, note_id: int) -> Notification:
        note = self._s.scalar(
            select(Notification).where(
                Notification.id == note_id, Notification.user_id == self._user_id
            )
        )
        if note is None:
            raise NotFoundError("Notification not found.")
        return note

    def mark_read(self, note_id: int) -> Notification:
        note = self._get(note_id)
        if note.read_at is None:
            note.read_at = self._now()
            self._s.commit()
        return note

    def mark_all_read(self) -> int:
        result = self._s.execute(
            update(Notification)
            .where(Notification.user_id == self._user_id, Notification.read_at.is_(None))
            .values(read_at=self._now())
        )
        self._s.commit()
        return result.rowcount

    def delete(self, note_id: int) -> None:
        self._s.delete(self._get(note_id))
        self._s.commit()
