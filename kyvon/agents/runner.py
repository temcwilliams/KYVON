"""Runs an agent: a bounded plan -> tool -> observe loop with full traceability.

Limits that hold on every run (whatever the model does):

* at most ``max_steps`` model calls and ``max_tool_calls`` tool calls
* a wall-clock deadline checked between steps (each model call and tool call has its own
  timeout as well, so a run can overshoot by at most one of those)
* agents cannot start agents: their tool allow-lists exclude ``delegate_to_agent`` and the
  runner refuses any depth beyond ``agent_max_depth``
* cooperative cancellation between steps
* tools an agent may call are limited to its allow-list; tools that need approval are queued
  for the user, never executed by the agent
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from kyvon.agents.definitions import DEFINITIONS, AgentDefinition
from kyvon.db import utcnow
from kyvon.models import AgentRun
from kyvon.services.environment_context import render_environment
from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure
from kyvon.services.settings_service import timezone_for
from kyvon.tools.executor import CallOrigin
from kyvon.utils.redact import redact

log = logging.getLogger("kyvon.agents")

MAX_GOAL = 2000
MAX_TRACE = 80
MAX_RESULT = 6000


def serialize_agent_run(run: AgentRun, *, include_trace: bool = False) -> dict:
    data = {
        "id": run.id,
        "agent": run.agent,
        "goal": redact(run.goal),
        "status": run.status,
        "origin": run.origin,
        "depth": run.depth,
        "conversation_id": run.conversation_id,
        "parent_run_id": run.parent_run_id,
        "result": redact(run.result) if run.result else None,
        "error": redact(run.error) if run.error else None,
        "steps": run.steps,
        "tool_calls": run.tool_calls,
        "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out,
        "model": run.model,
        "pending_run_ids": run.pending_run_ids or [],
        "cancel_requested": run.cancel_requested,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if include_trace:
        data["trace"] = run.trace or []
    return data


class AgentRunner:
    def __init__(
        self,
        services: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utcnow,
    ):
        self._services = services
        self._clock = clock
        self._now = now

    # ------------------------------------------------------------------ creation

    def definition(self, name: str) -> AgentDefinition:
        try:
            return DEFINITIONS[name]
        except KeyError:
            raise ValidationFailure(
                f"There is no agent called '{name}'. Available: {', '.join(sorted(DEFINITIONS))}."
            ) from None

    def create_run(
        self,
        session: Session,
        user_id: int,
        agent: str,
        goal: str,
        *,
        conversation_id: int | None = None,
        parent_run_id: int | None = None,
        depth: int = 1,
        origin: str = "chat",
    ) -> AgentRun:
        definition = self.definition(agent)
        goal = (goal or "").strip()
        if len(goal) < 5:
            raise ValidationFailure("Give the agent a clear goal.")
        if len(goal) > MAX_GOAL:
            raise ValidationFailure(f"Goals are limited to {MAX_GOAL} characters.")
        if depth > self._services.settings.agent_max_depth:
            raise ConflictError("Agents cannot start other agents.")
        if definition.backend == "hermes" and getattr(self._services, "hermes", None) is None:
            raise ConflictError("Hermes is not configured on this server.")
        run = AgentRun(
            user_id=user_id,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            agent=definition.name,
            goal=goal,
            origin=origin,
            depth=depth,
            status="queued",
            trace=[],
            created_at=self._now(),
        )
        session.add(run)
        session.commit()
        return run

    # ------------------------------------------------------------------ execution

    def run(self, session: Session, run_id: int) -> AgentRun:
        """Execute a queued run to completion (or until a limit is reached)."""
        run = session.get(AgentRun, run_id)
        if run is None:
            raise NotFoundError("Agent run not found.")
        if run.status != "queued":
            return run
        definition = self.definition(run.agent)
        settings = self._services.settings
        llm = self._llm_for(definition)
        model = self._model_for(definition)

        run.status = "running"
        run.started_at = self._now()
        run.model = model
        session.commit()

        deadline = self._clock() + min(
            definition.timeout_seconds, settings.agent_timeout_cap_seconds
        )
        max_tools = min(definition.max_tool_calls, settings.agent_max_tool_calls)
        allowed = set(definition.tools)
        origin = CallOrigin(
            run.user_id,
            run.conversation_id,
            agent_run_id=run.id,
            depth=run.depth,
            origin="agent",
        )
        specs = self._services.executor.specs(allowed)
        messages = [
            {"role": "system", "content": self._system_prompt(session, run, definition)},
            {"role": "user", "content": run.goal},
        ]
        trace: list[dict] = []
        pending: list[int] = []
        final_text = ""

        def note(entry: dict) -> None:
            if len(trace) < MAX_TRACE:
                trace.append(entry)

        try:
            for step in range(1, definition.max_steps + 1):
                stop = self._should_stop(session, run, deadline)
                if stop:
                    return self._finish(session, run, stop[0], final_text, stop[1], trace, pending)

                last_step = step == definition.max_steps
                started = self._clock()
                response = llm.chat(
                    messages,
                    model=model,
                    tools=None if last_step or not specs else specs,
                    temperature=definition.temperature,
                    max_tokens=1500,
                )
                run.steps += 1
                if response.usage:
                    run.tokens_in += response.usage.prompt_tokens or 0
                    run.tokens_out += response.usage.completion_tokens or 0
                note(
                    {
                        "step": step,
                        "kind": "llm",
                        "ms": int((self._clock() - started) * 1000),
                        "tool_calls": [c.name for c in response.tool_calls],
                    }
                )
                session.commit()

                if not response.tool_calls:
                    final_text = response.content
                    return self._finish(session, run, "succeeded", final_text, None, trace, pending)

                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments},
                            }
                            for c in response.tool_calls
                        ],
                    }
                )
                for call in response.tool_calls:
                    if run.tool_calls >= max_tools:
                        text = '{"ok": false, "error": "Tool call limit reached; finish with what you have."}'
                    else:
                        run.tool_calls += 1
                        began = self._clock()
                        outcome = self._services.executor.call(
                            session,
                            origin,
                            call.name,
                            call.arguments,
                            allowed=allowed,
                            call_id=call.id,
                        )
                        text = outcome.for_model()
                        if outcome.pending and outcome.run_id not in pending:
                            pending.append(outcome.run_id)
                        note(
                            {
                                "step": step,
                                "kind": "tool",
                                "name": call.name,
                                "status": outcome.status,
                                "tool_run_id": outcome.run_id,
                                "ms": int((self._clock() - began) * 1000),
                            }
                        )
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
                session.commit()

            # Out of steps without a final answer: ask for a report with what we have.
            messages.append(
                {"role": "user", "content": "Step limit reached. Give your final report now."}
            )
            response = llm.chat(
                messages, model=model, temperature=definition.temperature, max_tokens=800
            )
            run.steps += 1
            return self._finish(
                session, run, "succeeded", response.content, "Step limit reached.", trace, pending
            )
        except Exception as error:
            log.exception("agent run %s failed", run.id)
            session.rollback()
            run = session.get(AgentRun, run.id)
            self._services.error_log.log("Agent Error", f"{run.agent}: {error}", "")
            return self._finish(
                session,
                run,
                "failed",
                final_text,
                f"{type(error).__name__}: {error}",
                trace,
                pending,
            )

    # ------------------------------------------------------------------ helpers

    def _llm_for(self, definition: AgentDefinition):
        if definition.backend == "hermes":
            return self._services.hermes.llm
        return self._services.llm

    def _model_for(self, definition: AgentDefinition) -> str:
        if definition.backend == "hermes":
            return self._services.hermes.model
        return self._services.settings.model

    def _system_prompt(self, session: Session, run: AgentRun, definition: AgentDefinition) -> str:
        cached = self._services.environment_cache.get(run.user_id)
        tz = timezone_for(session, run.user_id, cached)
        return definition.prompt() + "\n\n" + render_environment(cached, timezone=tz)

    def _should_stop(self, session: Session, run: AgentRun, deadline: float):
        session.refresh(run)
        if run.cancel_requested:
            return "cancelled", "Cancelled by the user."
        if self._clock() >= deadline:
            return "timeout", "The agent ran out of time."
        return None

    def _finish(
        self,
        session: Session,
        run: AgentRun,
        status: str,
        result: str,
        error: str | None,
        trace: list[dict],
        pending: list[int],
    ) -> AgentRun:
        run.status = status
        run.result = (result or "")[:MAX_RESULT] or None
        run.error = error
        run.trace = list(trace)
        run.pending_run_ids = list(pending) or None
        run.finished_at = self._now()
        session.commit()
        return run
