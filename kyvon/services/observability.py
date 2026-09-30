"""Error records, system status and usage numbers for the owner's admin view.

Nothing here returns secrets: configuration is reported as yes/no, and free text is redacted.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import (
    AgentRun,
    Automation,
    CalendarAccount,
    Conversation,
    ErrorRecord,
    Memory,
    Message,
    Task,
    ToolRun,
    User,
)
from kyvon.utils.redact import redact

STARTED_AT = time.time()
MAX_MESSAGE = 1000
MAX_DETAILS = 4000


def record_error(
    session: Session, kind: str, message: str, details: str, *, request_id=None, user_id=None
) -> ErrorRecord:
    row = ErrorRecord(
        kind=kind[:64],
        message=redact(message)[:MAX_MESSAGE],
        details=redact(details)[:MAX_DETAILS],
        request_id=request_id,
        user_id=user_id,
        created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    return row


def serialize_error(e: ErrorRecord) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at.isoformat(),
        "kind": e.kind,
        "message": e.message,
        "details": e.details,
        "request_id": e.request_id,
        "resolved": e.resolved_at is not None,
        "resolution": e.resolution,
    }


def list_errors(
    session: Session, *, resolved: bool | None = None, limit: int = 50
) -> list[ErrorRecord]:
    query = select(ErrorRecord)
    if resolved is True:
        query = query.where(ErrorRecord.resolved_at.is_not(None))
    elif resolved is False:
        query = query.where(ErrorRecord.resolved_at.is_(None))
    return list(
        session.scalars(query.order_by(ErrorRecord.id.desc()).limit(max(1, min(limit, 200))))
    )


def resolve_error(session: Session, error_id: int, note: str = "") -> ErrorRecord | None:
    row = session.get(ErrorRecord, error_id)
    if row is None:
        return None
    row.resolved_at = utcnow()
    row.resolution = redact(note)[:500] or "Marked resolved"
    session.commit()
    return row


# ------------------------------------------------------------------ status


def database_status(session: Session, services: Any) -> dict:
    try:
        session.execute(text("SELECT 1"))
    except Exception as error:
        return {"ok": False, "error": type(error).__name__}
    info: dict = {"ok": True}
    try:
        current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        from alembic.script import ScriptDirectory

        from kyvon.db import alembic_config

        head = ScriptDirectory.from_config(
            alembic_config(services.settings.db_url)
        ).get_current_head()
        info.update(migration=current, migration_head=head, up_to_date=current == head)
    except Exception:
        info.update(migration=None, up_to_date=None)
    url = services.engine.url
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        try:
            import os

            info["size_bytes"] = os.path.getsize(url.database)
        except OSError:
            pass
    info["counts"] = {
        name: session.scalar(select(func.count()).select_from(model))
        for name, model in (
            ("users", User),
            ("conversations", Conversation),
            ("messages", Message),
            ("memories", Memory),
            ("tasks", Task),
            ("tool_runs", ToolRun),
            ("agent_runs", AgentRun),
            ("automations", Automation),
        )
    }
    return info


def system_status(
    session: Session, services: Any, *, deep: bool = False, now: datetime | None = None
) -> dict:
    now = now or utcnow()
    settings = services.settings
    day_ago = now - timedelta(days=1)
    status: dict[str, Any] = {
        "version": "1.0",
        "environment": settings.env,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "database": database_status(session, services),
    }

    # Language model: configured always; reachable only when asked (it costs one call).
    llm: dict[str, Any] = {
        "provider": "groq",
        "model": settings.model,
        "configured": bool(settings.groq_api_key),
    }
    if deep:
        try:
            reply = services.llm.complete(
                [{"role": "user", "content": "Reply with exactly: ONLINE"}],
                model=settings.model,
                temperature=0,
                max_tokens=10,
            )
            llm.update(reachable=True, reply=reply[:20])
        except Exception as error:
            llm.update(reachable=False, error=type(error).__name__)
    status["llm"] = llm

    hermes: dict[str, Any] = {"configured": services.hermes is not None}
    if deep and services.hermes is not None:
        hermes.update(services.hermes.health())
    status["integrations"] = {
        "calendar": {
            "configured": settings.calendar_configured,
            "connected_accounts": session.scalar(select(func.count()).select_from(CalendarAccount)),
        },
        "logseq": {"configured": services.logseq is not None},
        "hermes": {k: v for k, v in hermes.items() if k in ("configured", "reachable", "model")},
        "push": {"configured": settings.push_configured},
        "speech_to_text": {"configured": services.stt is not None},
    }

    scheduler = services.scheduler
    status["scheduler"] = {
        "enabled": settings.scheduler_enabled,
        "running": scheduler.running if scheduler else False,
        "last_tick_at": scheduler.last_tick_at.isoformat()
        if scheduler and scheduler.last_tick_at
        else None,
        "last_error": scheduler.last_error if scheduler else None,
        "enabled_automations": session.scalar(
            select(func.count()).select_from(Automation).where(Automation.enabled)
        ),
    }
    status["agents"] = {
        "running": session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.status == "running")
        ),
        "queued": session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.status == "queued")
        ),
    }
    status["tools"] = {
        "registered": len(services.registry.names()),
        "pending_approvals": session.scalar(
            select(func.count())
            .select_from(ToolRun)
            .where(ToolRun.status == "pending_confirmation")
        ),
        "failed_last_24h": session.scalar(
            select(func.count())
            .select_from(ToolRun)
            .where(ToolRun.status == "failed", ToolRun.created_at >= day_ago)
        ),
    }
    status["errors"] = {
        "unresolved": session.scalar(
            select(func.count()).select_from(ErrorRecord).where(ErrorRecord.resolved_at.is_(None))
        ),
        "last_24h": session.scalar(
            select(func.count()).select_from(ErrorRecord).where(ErrorRecord.created_at >= day_ago)
        ),
    }
    try:
        usage = shutil.disk_usage(settings.data_dir)
        status["disk"] = {"free_bytes": usage.free, "total_bytes": usage.total}
    except OSError:
        status["disk"] = None

    checks = [status["database"]["ok"], status["errors"]["last_24h"] < 50]
    if deep and llm.get("reachable") is False:
        checks.append(False)
    status["healthy"] = all(checks)
    return status


def usage_summary(session: Session, *, days: int = 7, now: datetime | None = None) -> dict:
    since = (now or utcnow()) - timedelta(days=days)
    tokens_in, tokens_out, replies = session.execute(
        select(
            func.coalesce(func.sum(Message.tokens_in), 0),
            func.coalesce(func.sum(Message.tokens_out), 0),
            func.count(),
        ).where(Message.role == "assistant", Message.kind == "message", Message.created_at >= since)
    ).one()
    agent_in, agent_out = session.execute(
        select(
            func.coalesce(func.sum(AgentRun.tokens_in), 0),
            func.coalesce(func.sum(AgentRun.tokens_out), 0),
        ).where(AgentRun.created_at >= since)
    ).one()
    by_tool = {
        name: count
        for name, count in session.execute(
            select(ToolRun.tool_name, func.count())
            .where(ToolRun.created_at >= since)
            .group_by(ToolRun.tool_name)
        )
    }
    by_status = {
        name: count
        for name, count in session.execute(
            select(ToolRun.status, func.count())
            .where(ToolRun.created_at >= since)
            .group_by(ToolRun.status)
        )
    }
    return {
        "days": days,
        "assistant_replies": replies,
        "chat_tokens": {"in": tokens_in, "out": tokens_out},
        "agent_tokens": {"in": agent_in, "out": agent_out},
        "tool_calls_by_tool": by_tool,
        "tool_calls_by_status": by_status,
    }
