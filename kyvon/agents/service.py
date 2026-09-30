"""Starting agent runs in the background, listing them and cancelling them."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import AgentRun
from kyvon.models.agent_run import FINISHED_STATUSES
from kyvon.services.errors import ConflictError, NotFoundError

log = logging.getLogger("kyvon.agents")


class AgentService:
    def __init__(self, services: Any):
        self._services = services
        self._pool = ThreadPoolExecutor(
            max_workers=services.settings.agent_max_concurrent, thread_name_prefix="kyvon-agent"
        )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def start(
        self,
        session: Session,
        user_id: int,
        agent: str,
        goal: str,
        *,
        conversation_id: int | None = None,
        origin: str = "api",
    ) -> AgentRun:
        """Queue a run and return immediately; it executes in a worker thread."""
        runner = self._services.agent_runner
        run = runner.create_run(
            session, user_id, agent, goal, conversation_id=conversation_id, depth=1, origin=origin
        )
        self._pool.submit(self._work, run.id)
        return run

    def _work(self, run_id: int) -> None:
        try:
            with self._services.session_factory() as session:
                self._services.agent_runner.run(session, run_id)
        except Exception:  # never let a worker die silently
            log.exception("agent worker crashed for run %s", run_id)

    def get(self, session: Session, user_id: int, run_id: int) -> AgentRun:
        run = session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )
        if run is None:
            raise NotFoundError("Agent run not found.")
        return run

    def list(self, session: Session, user_id: int, *, limit: int = 50) -> list[AgentRun]:
        return list(
            session.scalars(
                select(AgentRun)
                .where(AgentRun.user_id == user_id)
                .order_by(AgentRun.id.desc())
                .limit(max(1, min(limit, 200)))
            )
        )

    def cancel(self, session: Session, user_id: int, run_id: int) -> AgentRun:
        run = self.get(session, user_id, run_id)
        if run.status in FINISHED_STATUSES:
            raise ConflictError(f"That run has already {run.status}.")
        run.cancel_requested = True
        if run.status == "queued":  # not started yet: finish it now; the worker will skip it
            run.status = "cancelled"
            run.error = "Cancelled by the user."
            run.finished_at = utcnow()
        session.commit()
        return run

    def recover_orphans(self, session: Session) -> int:
        """Runs that were in flight when the process stopped can never finish: close them."""
        rows = list(
            session.scalars(select(AgentRun).where(AgentRun.status.in_(("queued", "running"))))
        )
        for run in rows:
            run.status = "failed"
            run.error = "Interrupted by a server restart."
            run.finished_at = utcnow()
        session.commit()
        return len(rows)
