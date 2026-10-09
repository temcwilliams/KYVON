"""Delegating work to a specialised agent."""

from __future__ import annotations

from pydantic import Field, field_validator

from kyvon.agents.definitions import DEFINITIONS
from kyvon.services.errors import ConflictError, ValidationFailure
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError, ToolResult
from kyvon.tools.registry import ToolRegistry


class DelegateArgs(ToolArgs):
    agent: str = Field(
        description="Which specialist to use.", json_schema_extra={"enum": sorted(DEFINITIONS)}
    )
    goal: str = Field(
        min_length=5,
        max_length=2000,
        description="A complete, self-contained description of what the specialist should achieve.",
    )

    @field_validator("agent")
    @classmethod
    def _known_agent(cls, value: str) -> str:
        if value not in DEFINITIONS:
            raise ValueError(f"unknown agent (choose one of: {', '.join(sorted(DEFINITIONS))})")
        return value


def available_agents(services) -> dict:
    """Agents that can run right now (Hermes only when it is configured)."""
    return {
        name: d
        for name, d in DEFINITIONS.items()
        if d.backend != "hermes" or getattr(services, "hermes", None) is not None
    }


def _catalogue(services) -> str:
    return " ".join(f"{d.name}: {d.description}" for d in available_agents(services).values())


def _spec(services) -> dict:
    """The function definition, listing only the agents that are usable right now."""
    agents = available_agents(services)
    schema = DelegateArgs.model_json_schema()
    properties = schema["properties"]
    properties["agent"] = {
        "type": "string",
        "description": "Which specialist to use.",
        "enum": sorted(agents),
    }
    for field in properties.values():
        field.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "description": DESCRIPTION + _catalogue(services),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": ["agent", "goal"],
                "additionalProperties": False,
            },
        },
    }


DESCRIPTION = (
    "Hand a complex, multi-step job to a specialist agent and get its report back. Use it "
    "only when the job needs several lookups or actions; answer simple requests yourself. "
    "Specialists: "
)


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "delegate_to_agent",
        DESCRIPTION,
        DelegateArgs,
        spec_factory=_spec,
        risk=RiskLevel.WRITE,  # agents may create tasks; anything consequential still needs approval
        timeout=240,
        untrusted_output=True,
        summarize=lambda a, ctx: f"Delegate to the {a.agent} agent: {a.goal[:200]}",
    )
    def delegate_to_agent(ctx: ToolContext, args: DelegateArgs):
        if ctx.depth >= ctx.settings.agent_max_depth:
            raise ToolError("Agents cannot start other agents.")
        runner = ctx.services.agent_runner
        try:
            run = runner.create_run(
                ctx.session,
                ctx.user_id,
                args.agent,
                args.goal,
                conversation_id=ctx.conversation_id,
                depth=ctx.depth + 1,
                origin=ctx.origin,
            )
        except (ValidationFailure, ConflictError) as problem:
            raise ToolError(str(problem)) from problem
        runner.run(ctx.session, run.id)
        ctx.session.refresh(run)
        return ToolResult(
            data={
                "agent": run.agent,
                "status": run.status,
                "report": run.result or run.error or "",
                "agent_run_id": run.id,
                "pending_run_ids": run.pending_run_ids or [],
                "tool_calls": run.tool_calls,
            },
            message=(
                "Some actions are waiting for the user's approval." if run.pending_run_ids else ""
            ),
        )
