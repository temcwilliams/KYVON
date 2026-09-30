"""Executes one automation run and does all the bookkeeping around it.

Safety properties:

* every run is recorded (status, result, error) in ``automation_runs``
* a failure is retried with a growing delay, and three failures in a row disable the
  automation and tell the user, so nothing can fail in a loop forever
* runs missed while the server was down are skipped after a grace period instead of
  firing a burst of stale notifications
* a scheduled task ("prompt") runs the normal assistant, so tools that need approval only
  queue an approval request; nothing consequential happens unattended
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from kyvon.automation.schedules import next_run
from kyvon.db import utcnow
from kyvon.models import Automation, AutomationRun
from kyvon.services.chat_factory import make_chat_service
from kyvon.services.conversation_service import ConversationService
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import NotFoundError
from kyvon.services.notification_service import NotificationService

log = logging.getLogger("kyvon.automation")

MAX_CONSECUTIVE_FAILURES = 3
RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=15))
MISSED_GRACE = timedelta(hours=12)
RESULT_LIMIT = 4000


class AutomationRunner:
    def __init__(self, services: Any, *, now: Callable[[], datetime] = utcnow):
        self._services = services
        self._now = now

    def execute(
        self,
        session: Session,
        automation_id: int,
        *,
        triggered_by: str = "schedule",
        scheduled_for: datetime | None = None,
    ) -> AutomationRun | None:
        automation = session.get(Automation, automation_id)
        if automation is None:
            return None
        now = self._now()
        scheduled = triggered_by in ("schedule", "retry")

        if scheduled and not automation.enabled:
            return None  # turned off between being claimed and running: cancelled

        run = AutomationRun(
            automation_id=automation.id,
            user_id=automation.user_id,
            triggered_by=triggered_by,
            status="running",
            scheduled_for=scheduled_for,
            started_at=now,
        )
        session.add(run)
        session.commit()

        if scheduled and scheduled_for is not None and now - scheduled_for > MISSED_GRACE:
            run.status = "skipped"
            run.result = "Missed while KYVON was not running; skipped."
            run.finished_at = self._now()
            self._advance(session, automation, scheduled_for=scheduled_for)
            session.commit()
            return run

        try:
            result = self._act(session, automation)
        except Exception as error:
            log.exception("automation %s failed", automation.id)
            self._services.error_log.log(
                "Automation Error", f"{automation.name}: {error}", traceback.format_exc()
            )
            session.rollback()
            automation = session.get(Automation, automation_id)
            run = session.get(AutomationRun, run.id)
            run.status = "failed"
            run.error = f"{type(error).__name__}: {error}"[:RESULT_LIMIT]
            run.finished_at = self._now()
            self._after_failure(session, automation, scheduled)
        else:
            run.status = "succeeded"
            run.result = (result or "")[:RESULT_LIMIT]
            run.finished_at = self._now()
            self._after_success(session, automation, scheduled, scheduled_for)
        session.commit()
        return run

    # ------------------------------------------------------------------ actions

    def _notifications(self, session: Session, user_id: int) -> NotificationService:
        return NotificationService(
            session, user_id, now=self._now, push=getattr(self._services, "push", None)
        )

    def _act(self, session: Session, automation: Automation) -> str:
        notes = self._notifications(session, automation.user_id)
        if automation.kind == "reminder":
            text = automation.payload["text"]
            notes.create(automation.name, text, automation_id=automation.id)
            return text

        # A scheduled task: run the assistant on the stored prompt in this automation's own
        # conversation, then put its answer in the inbox.
        conversations = ConversationService(session, automation.user_id)
        conversation_id = automation.payload.get("conversation_id")
        try:
            conversation = conversations.get(conversation_id) if conversation_id else None
        except NotFoundError:
            conversation = None
        if conversation is None:
            conversation = conversations.create(f"Automation: {automation.name}")
            automation.payload = {**automation.payload, "conversation_id": conversation.id}
            session.commit()

        chat = make_chat_service(self._services, session, automation.user_id)
        result = chat.reply(
            f"[Automated run of '{automation.name}'] {automation.payload['prompt']}",
            conversation.id,
        )
        body = result.message["content"]
        pending = result.flags.get("pending_confirmations") or []
        if pending:
            body += f"\n\n{len(pending)} action(s) are waiting for your approval."
        notes.create(
            automation.name, body, automation_id=automation.id, conversation_id=conversation.id
        )
        return body

    # ------------------------------------------------------------------ bookkeeping

    def _advance(
        self, session: Session, automation: Automation, *, scheduled_for: datetime | None = None
    ) -> None:
        """Schedule the next occurrence (or finish a one-time automation)."""
        tz = safe_zone(automation.timezone)
        base = max(self._now(), scheduled_for or self._now())
        upcoming = next_run(automation.schedule, tz, base)
        automation.next_run_at = upcoming
        if upcoming is None and automation.enabled:
            automation.enabled = False
            automation.disabled_reason = "Completed"

    def _after_success(
        self,
        session: Session,
        automation: Automation,
        scheduled: bool,
        scheduled_for: datetime | None,
    ) -> None:
        automation.run_count += 1
        automation.last_run_at = self._now()
        automation.last_status = "succeeded"
        automation.failure_count = 0
        if scheduled:
            self._advance(session, automation, scheduled_for=scheduled_for)

    def _after_failure(self, session: Session, automation: Automation, scheduled: bool) -> None:
        automation.run_count += 1
        automation.last_run_at = self._now()
        automation.last_status = "failed"
        automation.failure_count += 1
        if not scheduled:
            return  # a manual run's failure does not change the schedule
        if automation.failure_count >= MAX_CONSECUTIVE_FAILURES:
            automation.enabled = False
            automation.next_run_at = None
            automation.disabled_reason = (
                f"Turned off after {MAX_CONSECUTIVE_FAILURES} failures in a row"
            )
            self._notifications(session, automation.user_id).create(
                f"Automation turned off: {automation.name}",
                f"It failed {MAX_CONSECUTIVE_FAILURES} times in a row, so it was turned off. "
                "Check its history, fix it, and turn it back on.",
                source="system",
                automation_id=automation.id,
            )
            return
        delay = RETRY_DELAYS[min(automation.failure_count - 1, len(RETRY_DELAYS) - 1)]
        automation.next_run_at = self._now() + delay
