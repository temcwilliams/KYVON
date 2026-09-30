"""The background scheduler: finds due automations and runs them.

One daemon thread wakes up every ``scheduler_tick_seconds``, claims due automations with a
compare-and-swap UPDATE (so two processes can never run the same occurrence) and hands them
to a small worker pool. It only ever does work that is stored in the database; it has no
loops of its own to get out of hand.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from kyvon.automation.schedules import next_run
from kyvon.db import utcnow
from kyvon.models import Automation
from kyvon.services.environment_context import safe_zone

log = logging.getLogger("kyvon.scheduler")
BATCH = 20


class Scheduler:
    def __init__(
        self,
        services: Any,
        *,
        tick_seconds: float = 30.0,
        now: Callable[[], datetime] = utcnow,
        workers: int = 2,
    ):
        self._services = services
        self._tick_seconds = tick_seconds
        self._now = now
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kyvon-auto")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_at: datetime | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self.recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="kyvon-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                self.last_error = None
            except Exception as error:  # a bad tick must never kill the scheduler
                self.last_error = f"{type(error).__name__}: {error}"
                log.exception("scheduler tick failed")
            self._stop.wait(self._tick_seconds)

    # ------------------------------------------------------------------ work

    def recover(self) -> int:
        """Re-plan enabled automations that were claimed but never finished (a crash)."""
        fixed = 0
        try:
            with self._services.session_factory() as session:
                stuck = session.scalars(
                    select(Automation).where(Automation.enabled, Automation.next_run_at.is_(None))
                ).all()
                for automation in stuck:
                    tz = safe_zone(automation.timezone)
                    upcoming = next_run(automation.schedule, tz, self._now())
                    automation.next_run_at = upcoming
                    if upcoming is None:
                        automation.enabled = False
                        automation.disabled_reason = "Completed"
                    fixed += 1
                session.commit()
        except Exception:
            log.exception("scheduler recovery failed")
        return fixed

    def tick(self, now: datetime | None = None, *, inline: bool = False) -> int:
        """Dispatch everything that is due. ``inline`` runs them in this thread (for tests)."""
        current = now or self._now()
        dispatched: list[tuple[int, str, datetime]] = []
        with self._services.session_factory() as session:
            due = session.scalars(
                select(Automation)
                .where(Automation.enabled, Automation.next_run_at <= current)
                .order_by(Automation.next_run_at)
                .limit(BATCH)
            ).all()
            for automation in due:
                scheduled_for = automation.next_run_at
                claimed = session.execute(
                    update(Automation)
                    .where(
                        Automation.id == automation.id,
                        Automation.enabled,
                        Automation.next_run_at == scheduled_for,
                    )
                    .values(next_run_at=None)
                ).rowcount
                session.commit()
                if claimed == 1:
                    kind = "retry" if automation.failure_count else "schedule"
                    dispatched.append((automation.id, kind, scheduled_for))
        self.last_tick_at = current
        for automation_id, kind, scheduled_for in dispatched:
            if inline:
                self._run(automation_id, kind, scheduled_for)
            else:
                self._pool.submit(self._run, automation_id, kind, scheduled_for)
        return len(dispatched)

    def _run(self, automation_id: int, triggered_by: str, scheduled_for: datetime) -> None:
        runner = self._services.automation_runner
        try:
            with self._services.session_factory() as session:
                runner.execute(
                    session, automation_id, triggered_by=triggered_by, scheduled_for=scheduled_for
                )
        except Exception:
            log.exception("automation %s crashed", automation_id)
            self.recover()  # make sure it is planned again

    def run_now(self, automation_id: int) -> None:
        """Run an automation once, immediately, in the background (the 'Run now' button)."""
        self._pool.submit(self._run_manual, automation_id)

    def _run_manual(self, automation_id: int) -> None:
        try:
            with self._services.session_factory() as session:
                self._services.automation_runner.execute(
                    session, automation_id, triggered_by="manual"
                )
        except Exception:
            log.exception("manual automation %s crashed", automation_id)
