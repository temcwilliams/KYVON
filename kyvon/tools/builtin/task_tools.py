"""Task tools. Creating and editing tasks changes only KYVON's own data, so it needs no
confirmation; deleting a task does."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from kyvon.services.errors import NotFoundError, ValidationFailure
from kyvon.services.settings_service import timezone_for
from kyvon.services.task_service import UNSET, TaskService
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry

DUE_HELP = (
    "ISO 8601: a date (2026-10-03) or date-time (2026-10-03T14:00, in the user's time zone). "
    "Work out words like 'tomorrow' or 'Friday' from the current date in your context."
)
Priority = Literal["low", "normal", "high", "urgent"]
Recurrence = Literal["daily", "weekly", "monthly", "yearly"]


class CreateArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)
    priority: Priority = "normal"
    due: str | None = Field(default=None, max_length=40, description=DUE_HELP)
    recurrence: Recurrence | None = Field(default=None, description="Repeat after completion.")
    recurrence_interval: int = Field(default=1, ge=1, le=52, description="Every N days/weeks/...")


class ListArgs(ToolArgs):
    status: Literal["open", "done", "all"] = "open"
    overdue: bool | None = None
    priority: Priority | None = None
    due_before: str | None = Field(default=None, max_length=40, description=DUE_HELP)
    due_after: str | None = Field(default=None, max_length=40, description=DUE_HELP)
    query: str | None = Field(default=None, max_length=100, description="Words in title or notes.")
    limit: int = Field(default=25, ge=1, le=100)


class UpdateArgs(ToolArgs):
    task_id: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    due: str | None = Field(
        default=None, max_length=40, description=DUE_HELP + " Use 'none' to clear."
    )
    recurrence: Recurrence | Literal["none"] | None = None
    recurrence_interval: int | None = Field(default=None, ge=1, le=52)


class TaskIdArgs(ToolArgs):
    task_id: int = Field(ge=1)


def _service(ctx: ToolContext) -> TaskService:
    return TaskService(
        ctx.session,
        ctx.user_id,
        timezone=timezone_for(
            ctx.session, ctx.user_id, ctx.services.environment_cache.get(ctx.user_id)
        ),
        now=ctx.now,
    )


def _title(ctx: ToolContext | None, task_id: int) -> str:
    if ctx is None:
        return f"#{task_id}"
    try:
        return f'"{_service(ctx).get(task_id).title}"'
    except NotFoundError:
        return f"#{task_id} (not found)"


def _guard(action):
    try:
        return action()
    except (NotFoundError, ValidationFailure) as problem:
        raise ToolError(str(problem)) from problem


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "task_create",
        "Create a task or to-do item for the user, optionally with a due date, priority and "
        "repeat. Use this when the user asks to be reminded of, or to track, something to do.",
        CreateArgs,
        risk=RiskLevel.WRITE,
    )
    def task_create(ctx: ToolContext, args: CreateArgs):
        service = _service(ctx)
        task = _guard(
            lambda: service.create(
                args.title,
                notes=args.notes,
                priority=args.priority,
                due=args.due,
                recurrence=args.recurrence,
                recurrence_interval=args.recurrence_interval,
                source="assistant",
            )
        )
        return service.serialize(task)

    @registry.tool(
        "task_list",
        "List the user's tasks, filtered by status, priority, due dates, overdue or a search phrase.",
        ListArgs,
        untrusted_output=True,
    )
    def task_list(ctx: ToolContext, args: ListArgs):
        service = _service(ctx)
        rows = _guard(
            lambda: service.list(
                status=args.status,
                overdue=args.overdue,
                priority=args.priority,
                due_before=args.due_before,
                due_after=args.due_after,
                query=args.query,
                limit=args.limit,
            )
        )
        return [service.serialize(t) for t in rows]

    @registry.tool(
        "task_update",
        "Change a task's title, notes, priority, due date or repeat (find the id with task_list).",
        UpdateArgs,
        risk=RiskLevel.WRITE,
    )
    def task_update(ctx: ToolContext, args: UpdateArgs):
        fields = args.model_fields_set - {"task_id"}
        if not fields:
            raise ToolError("Nothing to change.")
        changes: dict = {}
        for name in ("title", "notes", "priority", "recurrence_interval"):
            if name in fields and getattr(args, name) is not None:
                changes[name] = getattr(args, name)
        if "due" in fields:
            changes["due"] = None if args.due in (None, "", "none") else args.due
        if "recurrence" in fields:
            changes["recurrence"] = None if args.recurrence in (None, "none") else args.recurrence
        service = _service(ctx)
        return service.serialize(_guard(lambda: service.update(args.task_id, **changes)))

    @registry.tool(
        "task_complete",
        "Mark a task as done. A repeating task automatically gets its next occurrence.",
        TaskIdArgs,
        risk=RiskLevel.WRITE,
    )
    def task_complete(ctx: ToolContext, args: TaskIdArgs):
        service = _service(ctx)
        task, follow_up = _guard(lambda: service.complete(args.task_id))
        return {
            "task": service.serialize(task),
            "next_task": service.serialize(follow_up) if follow_up else None,
        }

    @registry.tool(
        "task_reopen", "Mark a completed task as open again.", TaskIdArgs, risk=RiskLevel.WRITE
    )
    def task_reopen(ctx: ToolContext, args: TaskIdArgs):
        service = _service(ctx)
        return service.serialize(_guard(lambda: service.reopen(args.task_id)))

    @registry.tool(
        "task_delete",
        "Permanently delete a task. The user must approve. (Completing a task is usually better.)",
        TaskIdArgs,
        risk=RiskLevel.DESTRUCTIVE,
        summarize=lambda a, ctx: f"Delete the task {_title(ctx, a.task_id)}",
    )
    def task_delete(ctx: ToolContext, args: TaskIdArgs):
        _guard(lambda: _service(ctx).delete(args.task_id))
        return {"deleted": args.task_id}


__all__ = ["UNSET", "register"]
