"""Let the assistant read the user's preferences, and propose changing a few of them.

Changes need the user's approval, and free-text ``assistant_notes`` is not settable here at
all: a persisted instruction is exactly what a prompt-injection attack would want to plant.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from kyvon.services.errors import ValidationFailure
from kyvon.services.settings_service import ASSISTANT_EDITABLE, get_settings, update_settings
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry


class NoArgs(ToolArgs):
    pass


class UpdateArgs(ToolArgs):
    display_name: str | None = Field(
        default=None, max_length=60, description="What to call the user."
    )
    response_style: Literal["concise", "balanced", "detailed"] | None = None
    tone: Literal["default", "warm", "formal", "playful"] | None = None
    units: Literal["imperial", "metric"] | None = None
    language: str | None = Field(default=None, min_length=1, max_length=30)
    timezone: str | None = Field(
        default=None, max_length=64, description="IANA name, e.g. America/Chicago."
    )
    week_starts_on: Literal["sun", "mon"] | None = None


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "settings_get",
        "Read the user's preferences (name, response style, units, time zone, ...).",
        NoArgs,
    )
    def settings_get(ctx: ToolContext, args: NoArgs):
        data = get_settings(ctx.session, ctx.user_id).model_dump()
        data.pop("assistant_notes", None)  # the user's own notes are not echoed back
        return data

    @registry.tool(
        "settings_update",
        "Propose changing the user's preferences when they ask (for example 'call me Sam', "
        "'answer more briefly', 'use metric'). The user must approve.",
        UpdateArgs,
        risk=RiskLevel.WRITE,
        confirm=True,
        summarize=lambda a, ctx: (
            "Change your settings: "
            + ", ".join(f"{k} → {v}" for k, v in a.model_dump(exclude_none=True).items())
        ),
    )
    def settings_update(ctx: ToolContext, args: UpdateArgs):
        changes = args.model_dump(exclude_none=True)
        if not changes:
            raise ToolError("Nothing to change.")
        if not set(changes) <= set(
            ASSISTANT_EDITABLE
        ):  # defence in depth; the schema already limits this
            raise ToolError("Those settings cannot be changed by the assistant.")
        try:
            saved = update_settings(ctx.session, ctx.user_id, changes)
        except ValidationFailure as problem:
            raise ToolError(str(problem)) from problem
        return {k: getattr(saved, k) for k in changes}
