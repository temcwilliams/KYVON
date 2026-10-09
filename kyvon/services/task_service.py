"""Tasks: create, update, complete (with recurrence), reopen, delete, list. User-scoped."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Task
from kyvon.models.task import PRIORITIES, RECURRENCES
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import NotFoundError, ValidationFailure
from kyvon.services.settings_service import timezone_for
from kyvon.services.tasks_time import is_overdue, next_occurrence, parse_due, to_local_iso

MAX_TITLE = 200
MAX_NOTES = 2000
UNSET = object()  # "leave unchanged" (None means "clear")


def priority_value(value) -> int:
    """Accept 1-4 or a name (low, normal, high, urgent)."""
    if isinstance(value, str):
        by_name = {name: number for number, name in PRIORITIES.items()}
        if value.strip().lower() in by_name:
            return by_name[value.strip().lower()]
        raise ValidationFailure("Priority must be low, normal, high or urgent.")
    if isinstance(value, bool) or not isinstance(value, int) or value not in PRIORITIES:
        raise ValidationFailure("Priority must be 1 (low) to 4 (urgent).")
    return value


def clean_title(title: str) -> str:
    cleaned = " ".join((title or "").split())
    if not cleaned:
        raise ValidationFailure("A task needs a title.")
    if len(cleaned) > MAX_TITLE:
        raise ValidationFailure(f"Titles are limited to {MAX_TITLE} characters.")
    return cleaned


class TaskService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        timezone: str | None = None,
        now: Callable[[], datetime] = utcnow,
    ):
        self._s = session
        self._user_id = user_id
        self._now = now
        self._tz_name = timezone

    @property
    def tz(self):
        return safe_zone(self._tz_name or timezone_for(self._s, self._user_id))

    # ------------------------------------------------------------ serialization

    def serialize(self, task: Task) -> dict:
        tz = self.tz
        return {
            "id": task.id,
            "title": task.title,
            "notes": task.notes,
            "status": task.status,
            "priority": task.priority,
            "priority_name": PRIORITIES.get(task.priority, "normal"),
            "due": to_local_iso(task.due_at, task.due_has_time, tz),
            "due_has_time": task.due_has_time,
            "overdue": task.status == "open"
            and is_overdue(task.due_at, task.due_has_time, self._now(), tz),
            "recurrence": task.recurrence,
            "recurrence_interval": task.recurrence_interval,
            "source": task.source,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

    # ------------------------------------------------------------ queries

    def get(self, task_id: int) -> Task:
        task = self._s.scalar(select(Task).where(Task.id == task_id, Task.user_id == self._user_id))
        if task is None:
            raise NotFoundError("Task not found.")
        return task

    def list(
        self,
        *,
        status: str = "open",
        priority: int | str | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
        overdue: bool | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[Task]:
        if status not in ("open", "done", "all"):
            raise ValidationFailure("status must be open, done or all.")
        stmt = select(Task).where(Task.user_id == self._user_id)
        if status != "all":
            stmt = stmt.where(Task.status == status)
        if priority is not None:
            stmt = stmt.where(Task.priority == priority_value(priority))
        tz = self.tz
        if due_before:
            stmt = stmt.where(Task.due_at.is_not(None), Task.due_at < parse_due(due_before, tz)[0])
        if due_after:
            stmt = stmt.where(Task.due_at.is_not(None), Task.due_at >= parse_due(due_after, tz)[0])
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            stmt = stmt.where(
                or_(Task.title.like(like, escape="\\"), Task.notes.like(like, escape="\\"))
            )
        # Open tasks: soonest due first, undated last, then higher priority. Done: newest first.
        if status == "done":
            stmt = stmt.order_by(Task.completed_at.desc(), Task.id.desc())
        else:
            stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at, Task.priority.desc(), Task.id)
        rows = list(self._s.scalars(stmt.limit(max(1, min(limit, 500)))))
        if overdue is not None:
            now, tz = self._now(), self.tz
            rows = [
                t
                for t in rows
                if (t.status == "open" and is_overdue(t.due_at, t.due_has_time, now, tz)) == overdue
            ]
        return rows

    def count_open(self) -> int:
        return self._s.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == self._user_id, Task.status == "open")
        )

    # ------------------------------------------------------------ changes

    def create(
        self,
        title: str,
        *,
        notes: str = "",
        priority: int | str = 2,
        due: str | None = None,
        recurrence: str | None = None,
        recurrence_interval: int = 1,
        source: str = "user",
    ) -> Task:
        task = Task(
            user_id=self._user_id,
            title=clean_title(title),
            notes=self._notes(notes),
            priority=priority_value(priority),
            source=source,
            created_at=self._now(),
            updated_at=self._now(),
        )
        if due:
            task.due_at, task.due_has_time = parse_due(due, self.tz)
        self._set_recurrence(task, recurrence, recurrence_interval)
        self._s.add(task)
        self._s.commit()
        return task

    def update(
        self,
        task_id: int,
        *,
        title=UNSET,
        notes=UNSET,
        priority=UNSET,
        due=UNSET,
        recurrence=UNSET,
        recurrence_interval=UNSET,
    ) -> Task:
        task = self.get(task_id)
        if title is not UNSET:
            task.title = clean_title(title)
        if notes is not UNSET:
            task.notes = self._notes(notes)
        if priority is not UNSET:
            task.priority = priority_value(priority)
        if due is not UNSET:
            if due in (None, ""):
                task.due_at, task.due_has_time = None, True
            else:
                task.due_at, task.due_has_time = parse_due(due, self.tz)
        if recurrence is not UNSET or recurrence_interval is not UNSET:
            self._set_recurrence(
                task,
                task.recurrence if recurrence is UNSET else recurrence,
                task.recurrence_interval if recurrence_interval is UNSET else recurrence_interval,
            )
        task.updated_at = self._now()
        self._s.commit()
        return task

    def complete(self, task_id: int) -> tuple[Task, Task | None]:
        """Mark done. A recurring task also spawns its next occurrence."""
        task = self.get(task_id)
        if task.status == "done":
            return task, None
        task.status = "done"
        task.completed_at = self._now()
        task.updated_at = self._now()
        follow_up = None
        if task.recurrence:
            base = task.due_at or self._now()
            follow_up = Task(
                user_id=self._user_id,
                title=task.title,
                notes=task.notes,
                priority=task.priority,
                due_at=next_occurrence(base, task.recurrence, task.recurrence_interval, self.tz),
                due_has_time=task.due_has_time,
                recurrence=task.recurrence,
                recurrence_interval=task.recurrence_interval,
                source=task.source,
                created_at=self._now(),
                updated_at=self._now(),
            )
            # Catch up if the task was completed long after its due date.
            for _ in range(1000):
                if follow_up.due_at > self._now():
                    break
                follow_up.due_at = next_occurrence(
                    follow_up.due_at, task.recurrence, task.recurrence_interval, self.tz
                )
            self._s.add(follow_up)
        self._s.commit()
        return task, follow_up

    def reopen(self, task_id: int) -> Task:
        task = self.get(task_id)
        task.status = "open"
        task.completed_at = None
        task.updated_at = self._now()
        self._s.commit()
        return task

    def delete(self, task_id: int) -> None:
        self._s.delete(self.get(task_id))
        self._s.commit()

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _notes(notes: str | None) -> str:
        text = (notes or "").strip()
        if len(text) > MAX_NOTES:
            raise ValidationFailure(f"Notes are limited to {MAX_NOTES} characters.")
        return text

    @staticmethod
    def _set_recurrence(task: Task, recurrence: str | None, interval: int) -> None:
        if not recurrence:
            task.recurrence, task.recurrence_interval = None, 1
            return
        if recurrence not in RECURRENCES:
            raise ValidationFailure(f"Recurrence must be one of: {', '.join(RECURRENCES)}.")
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 52:
            raise ValidationFailure("The repeat interval must be between 1 and 52.")
        if task.due_at is None:
            raise ValidationFailure("A repeating task needs a due date.")
        task.recurrence, task.recurrence_interval = recurrence, interval
