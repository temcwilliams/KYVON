"""Automation tools. Creating an automation sets up a standing rule, so it needs approval."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from kyvon.automation.schedules import describe, validate_schedule
from kyvon.services.automation_service import AutomationService, serialize_automation
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure
from kyvon.services.settings_service import timezone_for
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CreateArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=120, description="A short title.")
    kind: Literal["reminder", "prompt"] = Field(
        description="reminder: show a message. prompt: run KYVON on the message each time and send the result."
    )
    message: str = Field(
        min_length=1,
        max_length=1000,
        description="Reminder text, or what KYVON should do each time (e.g. 'Summarise my upcoming week from my calendar and tasks').",
    )
    schedule_type: Literal["once", "daily", "weekly", "monthly", "interval"]
    at: str | None = Field(
        default=None, max_length=20, description="once: local date-time, 2026-10-03T08:00"
    )
    time: str | None = Field(
        default=None, max_length=5, description="daily/weekly/monthly: 24-hour HH:MM"
    )
    days: list[Weekday] | None = Field(default=None, description="weekly: which days")
    day_of_month: int | None = Field(default=None, ge=1, le=31, description="monthly")
    every_minutes: int | None = Field(
        default=None, ge=15, le=10080, description="interval (minimum 15)"
    )


class ListArgs(ToolArgs):
    pass


class IdArgs(ToolArgs):
    automation_id: int = Field(ge=1)


class EnableArgs(ToolArgs):
    automation_id: int = Field(ge=1)
    enabled: bool


def build_schedule(args: CreateArgs) -> dict:
    kind = args.schedule_type
    if kind == "once":
        return {"type": "once", "at": args.at or ""}
    if kind == "daily":
        return {"type": "daily", "time": args.time or ""}
    if kind == "weekly":
        return {"type": "weekly", "days": list(args.days or []), "time": args.time or ""}
    if kind == "monthly":
        return {"type": "monthly", "day": args.day_of_month, "time": args.time or ""}
    return {"type": "interval", "minutes": args.every_minutes}


def _service(ctx: ToolContext) -> AutomationService:
    return AutomationService(
        ctx.session,
        ctx.user_id,
        max_automations=ctx.settings.automation_max_per_user,
        timezone=timezone_for(
            ctx.session, ctx.user_id, ctx.services.environment_cache.get(ctx.user_id)
        ),
        now=ctx.now,
    )


def _guard(action):
    try:
        return action()
    except (ValidationFailure, NotFoundError, ConflictError) as problem:
        raise ToolError(str(problem)) from problem


def _create_summary(args: CreateArgs, ctx: ToolContext | None) -> str:
    when = args.schedule_type
    if ctx is not None:
        try:
            tz = safe_zone(
                timezone_for(
                    ctx.session, ctx.user_id, ctx.services.environment_cache.get(ctx.user_id)
                )
            )
            when = describe(validate_schedule(build_schedule(args), tz))
        except ValidationFailure as problem:
            when = f"(invalid schedule: {problem})"
    what = "remind you" if args.kind == "reminder" else "run this task"
    return f'Create the automation "{args.name}": {when} — {what}: "{args.message[:200]}"'


def _automation_label(ctx: ToolContext | None, automation_id: int) -> str:
    if ctx is None:
        return f"#{automation_id}"
    try:
        return f'"{_service(ctx).get(automation_id).name}"'
    except NotFoundError:
        return f"#{automation_id} (not found)"


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "automation_create",
        "Set up a reminder or a recurring scheduled task (for example 'remind me tomorrow at 8 AM', "
        "'every Sunday summarise my week', 'every evening remind me to review my tasks'). It "
        "creates a standing rule, so the user must approve it.",
        CreateArgs,
        risk=RiskLevel.WRITE,
        confirm=True,
        summarize=_create_summary,
    )
    def automation_create(ctx: ToolContext, args: CreateArgs):
        service = _service(ctx)
        automation = _guard(
            lambda: service.create(
                args.name,
                args.kind,
                build_schedule(args),
                text=args.message if args.kind == "reminder" else None,
                prompt=args.message if args.kind == "prompt" else None,
                source="assistant",
            )
        )
        return serialize_automation(automation)

    @registry.tool("automation_list", "List the user's automations and reminders.", ListArgs)
    def automation_list(ctx: ToolContext, args: ListArgs):
        return [serialize_automation(a) for a in _service(ctx).list()]

    @registry.tool(
        "automation_set_enabled",
        "Turn an automation on or off without deleting it.",
        EnableArgs,
        risk=RiskLevel.WRITE,
    )
    def automation_set_enabled(ctx: ToolContext, args: EnableArgs):
        service = _service(ctx)
        return serialize_automation(
            _guard(lambda: service.update(args.automation_id, enabled=args.enabled))
        )

    @registry.tool(
        "automation_delete",
        "Permanently delete an automation. The user must approve.",
        IdArgs,
        risk=RiskLevel.DESTRUCTIVE,
        summarize=lambda a, ctx: f"Delete the automation {_automation_label(ctx, a.automation_id)}",
    )
    def automation_delete(ctx: ToolContext, args: IdArgs):
        _guard(lambda: _service(ctx).delete(args.automation_id))
        return {"deleted": args.automation_id}
