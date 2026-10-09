"""Read-only diagnostics tools (used by the diagnostics agent and available to the assistant)."""

from __future__ import annotations

from pydantic import Field
from sqlalchemy import select

from kyvon.models import ToolRun
from kyvon.services import observability
from kyvon.tools.base import ToolArgs, ToolContext
from kyvon.tools.registry import ToolRegistry


class NoArgs(ToolArgs):
    pass


class ErrorsArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=30)


class RunsArgs(ToolArgs):
    status: str | None = Field(
        default=None, max_length=24, description="e.g. failed, pending_confirmation"
    )
    limit: int = Field(default=10, ge=1, le=30)


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "system_status",
        "Check KYVON's own health: database, integrations, scheduler, agents and recent errors.",
        NoArgs,
    )
    def system_status(ctx: ToolContext, args: NoArgs):
        status = observability.system_status(ctx.session, ctx.services)
        status["database"].pop("counts", None)
        return status

    @registry.tool(
        "recent_errors",
        "List KYVON's recent unresolved errors (kind, message, when) to help explain a problem.",
        ErrorsArgs,
        untrusted_output=True,
    )
    def recent_errors(ctx: ToolContext, args: ErrorsArgs):
        rows = observability.list_errors(ctx.session, resolved=False, limit=args.limit)
        return [
            {
                "id": e.id,
                "when": e.created_at.isoformat(),
                "kind": e.kind,
                "message": e.message[:300],
            }
            for e in rows
        ]

    @registry.tool(
        "recent_tool_runs",
        "List recent tool executions and their outcomes (audit trail), optionally by status.",
        RunsArgs,
        untrusted_output=True,
    )
    def recent_tool_runs(ctx: ToolContext, args: RunsArgs):
        query = select(ToolRun).where(ToolRun.user_id == ctx.user_id)
        if args.status:
            query = query.where(ToolRun.status == args.status)
        rows = ctx.session.scalars(query.order_by(ToolRun.id.desc()).limit(args.limit))
        return [
            {
                "id": r.id,
                "tool": r.tool_name,
                "status": r.status,
                "summary": r.summary[:200],
                "error": (r.error or "")[:200],
                "when": r.created_at.isoformat(),
            }
            for r in rows
        ]
