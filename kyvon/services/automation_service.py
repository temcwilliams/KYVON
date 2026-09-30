"""Creating, editing and inspecting automations (always scoped to one user)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kyvon.automation.schedules import describe, next_run, validate_schedule
from kyvon.db import utcnow
from kyvon.models import Automation, AutomationRun
from kyvon.models.automation import KINDS
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure
from kyvon.services.settings_service import timezone_for

MAX_NAME = 120
MAX_TEXT = 500
MAX_PROMPT = 1000


def serialize_automation(a: Automation) -> dict:
    tz = safe_zone(a.timezone)
    next_local = a.next_run_at.astimezone(tz).isoformat() if a.next_run_at else None
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "text": a.payload.get("text") if a.kind == "reminder" else None,
        "prompt": a.payload.get("prompt") if a.kind == "prompt" else None,
        "conversation_id": a.payload.get("conversation_id"),
        "schedule": a.schedule,
        "schedule_text": describe(a.schedule),
        "timezone": a.timezone,
        "enabled": a.enabled,
        "disabled_reason": a.disabled_reason,
        "source": a.source,
        "next_run_at": next_local,
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "last_status": a.last_status,
        "run_count": a.run_count,
        "failure_count": a.failure_count,
        "created_at": a.created_at.isoformat(),
    }


def serialize_run(r: AutomationRun) -> dict:
    return {
        "id": r.id,
        "automation_id": r.automation_id,
        "triggered_by": r.triggered_by,
        "status": r.status,
        "result": r.result,
        "error": r.error,
        "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


class AutomationService:
    def __init__(
        self,
        session: Session,
        user_id: int,
        *,
        max_automations: int = 50,
        timezone: str | None = None,
        now: Callable[[], datetime] = utcnow,
    ):
        self._s = session
        self._user_id = user_id
        self._max = max_automations
        self._tz_name = timezone
        self._now = now

    def _default_tz(self) -> str:
        return self._tz_name or timezone_for(self._s, self._user_id)

    # ------------------------------------------------------------ queries

    def get(self, automation_id: int) -> Automation:
        automation = self._s.scalar(
            select(Automation).where(
                Automation.id == automation_id, Automation.user_id == self._user_id
            )
        )
        if automation is None:
            raise NotFoundError("Automation not found.")
        return automation

    def list(self) -> list[Automation]:
        return list(
            self._s.scalars(
                select(Automation)
                .where(Automation.user_id == self._user_id)
                .order_by(Automation.id.desc())
            )
        )

    def runs(self, automation_id: int, limit: int = 20) -> list[AutomationRun]:
        self.get(automation_id)
        return list(
            self._s.scalars(
                select(AutomationRun)
                .where(AutomationRun.automation_id == automation_id)
                .order_by(AutomationRun.id.desc())
                .limit(max(1, min(limit, 100)))
            )
        )

    # ------------------------------------------------------------ changes

    @staticmethod
    def _payload(kind: str, text: str | None, prompt: str | None) -> dict:
        if kind == "reminder":
            cleaned = " ".join((text or "").split())
            if not cleaned:
                raise ValidationFailure("A reminder needs some text.")
            if len(cleaned) > MAX_TEXT:
                raise ValidationFailure(f"Reminder text is limited to {MAX_TEXT} characters.")
            return {"text": cleaned}
        cleaned = " ".join((prompt or "").split())
        if not cleaned:
            raise ValidationFailure("A scheduled task needs a prompt.")
        if len(cleaned) > MAX_PROMPT:
            raise ValidationFailure(f"Prompts are limited to {MAX_PROMPT} characters.")
        return {"prompt": cleaned}

    def create(
        self,
        name: str,
        kind: str,
        schedule: dict,
        *,
        text: str | None = None,
        prompt: str | None = None,
        timezone: str | None = None,
        source: str = "user",
    ) -> Automation:
        name = " ".join((name or "").split())
        if not name or len(name) > MAX_NAME:
            raise ValidationFailure(f"A name of 1-{MAX_NAME} characters is required.")
        if kind not in KINDS:
            raise ValidationFailure("Kind must be 'reminder' or 'prompt'.")
        count = self._s.scalar(
            select(func.count()).select_from(Automation).where(Automation.user_id == self._user_id)
        )
        if count >= self._max:
            raise ConflictError(f"You can have at most {self._max} automations.")

        tz_name = timezone or self._default_tz()
        tz = safe_zone(tz_name)
        spec = validate_schedule(schedule, tz)
        first = next_run(spec, tz, self._now())
        if first is None:
            raise ValidationFailure("That time has already passed.")

        automation = Automation(
            user_id=self._user_id,
            name=name,
            kind=kind,
            payload=self._payload(kind, text, prompt),
            schedule=spec,
            timezone=str(tz),
            enabled=True,
            source=source,
            next_run_at=first,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._s.add(automation)
        self._s.commit()
        return automation

    def update(
        self,
        automation_id: int,
        *,
        name: str | None = None,
        schedule: dict | None = None,
        text: str | None = None,
        prompt: str | None = None,
        enabled: bool | None = None,
    ) -> Automation:
        automation = self.get(automation_id)
        tz = safe_zone(automation.timezone)
        if name is not None:
            cleaned = " ".join(name.split())
            if not cleaned or len(cleaned) > MAX_NAME:
                raise ValidationFailure(f"A name of 1-{MAX_NAME} characters is required.")
            automation.name = cleaned
        if text is not None or prompt is not None:
            payload = dict(automation.payload)
            payload.update(self._payload(automation.kind, text, prompt))
            automation.payload = payload
        if schedule is not None:
            automation.schedule = validate_schedule(schedule, tz)
        if schedule is not None or enabled is True:
            upcoming = next_run(automation.schedule, tz, self._now())
            if upcoming is None and (enabled is not False):
                raise ValidationFailure("That time has already passed.")
            automation.next_run_at = upcoming
        if enabled is not None:
            automation.enabled = enabled
            if enabled:
                automation.disabled_reason = None
                automation.failure_count = 0
            else:
                automation.next_run_at = None
                automation.disabled_reason = "Turned off"
        automation.updated_at = self._now()
        self._s.commit()
        return automation

    def delete(self, automation_id: int) -> None:
        self._s.delete(self.get(automation_id))
        self._s.commit()
