"""Tool definitions: the only way KYVON can act.

A tool is a named, schema-validated, permission-classified function. The model never
receives code execution or free-form system access; it can only ask for these tools by
name, with arguments that are validated before anything runs.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


class RiskLevel(enum.StrEnum):
    READ = "read"  # reads data; no side effects
    WRITE = "write"  # changes KYVON's own data in a reversible way
    EXTERNAL = "external"  # has effects outside KYVON (calendar, notes, other services)
    DESTRUCTIVE = "destructive"  # deletes or overwrites something


CONFIRMATION_RISKS = frozenset({RiskLevel.EXTERNAL, RiskLevel.DESTRUCTIVE})


class ToolArgs(BaseModel):
    """Base for tool argument models: unknown fields are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolError(Exception):
    """An expected failure the model should hear about (bad id, not connected, ...).

    Never retried. The message is shown to the model, so keep it free of secrets.
    """


@dataclass
class ToolResult:
    data: Any = None
    message: str = ""
    # True when the content came from outside KYVON (web pages, notes, calendar text).
    # It is passed to the model as data, never as instructions.
    untrusted: bool = False


@dataclass
class ToolContext:
    """Everything a tool may use. Tools get no Flask globals and no shell."""

    session: Any  # sqlalchemy Session owned by this execution
    user_id: int
    services: Any  # kyvon.Services
    conversation_id: int | None = None
    agent_run_id: int | None = None
    depth: int = 0
    origin: str = "chat"  # chat | agent | automation | api
    now: Callable = field(default=None)  # type: ignore[assignment]

    @property
    def settings(self):
        return self.services.settings


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Callable[[ToolContext, Any], Any]
    risk: RiskLevel = RiskLevel.READ
    confirm: bool | None = None  # None: derived from ``risk``
    # Human text shown when asking to confirm: summarize(args, ctx) -> str. It is written in
    # code (never by the model), so the wording of a confirmation cannot be manipulated.
    summarize: Callable[[Any, Any], str] | None = None
    timeout: int | None = None  # seconds; default comes from settings
    retries: int = 0  # extra attempts on unexpected errors; READ tools only
    untrusted_output: bool = False
    enabled: Callable[[Any], bool] | None = None  # hide the tool when this returns False

    @property
    def requires_confirmation(self) -> bool:
        if self.confirm is not None:
            return self.confirm
        return self.risk in CONFIRMATION_RISKS

    def is_enabled(self, services: Any) -> bool:
        return self.enabled(services) if self.enabled else True

    def describe(self, args: Any, ctx: Any = None) -> str:
        if self.summarize:
            try:
                return self.summarize(args, ctx)[:500]
            except Exception:  # a summary must never block the action from being asked
                pass
        return f"Run {self.name}"

    def spec(self) -> dict:
        """The OpenAI-style function definition sent to the model."""
        schema = self.args_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(schema),
            },
        }


def _clean_schema(schema: dict) -> dict:
    """Drop pydantic noise that providers do not need (titles) and forbid extra properties."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs.get(node["$ref"].split("/")[-1], {}))
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "$defs")}
            if out.get("type") == "object":
                out.setdefault("properties", {})
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    cleaned = walk(schema)
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    return cleaned
