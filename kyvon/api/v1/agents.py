"""Agents: what exists, start a run, follow it, cancel it."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from kyvon.agents.definitions import DEFINITIONS
from kyvon.agents.runner import serialize_agent_run
from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import AgentRunCreate
from kyvon.models import ToolRun
from kyvon.services.conversation_service import ConversationService
from kyvon.tools.builtin.agent_tools import available_agents
from kyvon.tools.executor import serialize_tool_run

bp = Blueprint("agents", __name__, url_prefix="/api/v1/agents")


@bp.get("")
@login_required
def list_agents():
    usable = available_agents(services())
    return jsonify(
        {
            "agents": [
                {
                    "name": d.name,
                    "available": d.name in usable,
                    "role": d.role,
                    "description": d.description,
                    "tools": list(d.tools),
                    "max_steps": d.max_steps,
                    "max_tool_calls": d.max_tool_calls,
                    "timeout_seconds": d.timeout_seconds,
                    "backend": d.backend,
                }
                for d in DEFINITIONS.values()
            ]
        }
    )


@bp.post("/runs")
@login_required
def start_run():
    body = parse_json(AgentRunCreate)
    session = get_session()
    if body.conversation_id is not None:
        ConversationService(session, g.user.id).get(body.conversation_id)  # ownership check
    run = services().agent_service.start(
        session, g.user.id, body.agent, body.goal, conversation_id=body.conversation_id
    )
    return jsonify({"run": serialize_agent_run(run)}), 202


@bp.get("/runs")
@login_required
def list_runs():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        raise ApiError(400, "invalid_request", "limit must be an integer.") from None
    rows = services().agent_service.list(get_session(), g.user.id, limit=limit)
    return jsonify({"runs": [serialize_agent_run(r) for r in rows]})


@bp.get("/runs/<int:run_id>")
@login_required
def get_run(run_id: int):
    session = get_session()
    run = services().agent_service.get(session, g.user.id, run_id)
    tool_runs = session.scalars(
        select(ToolRun).where(ToolRun.agent_run_id == run.id).order_by(ToolRun.id)
    )
    return jsonify(
        {
            "run": serialize_agent_run(run, include_trace=True),
            "tool_runs": [serialize_tool_run(t) for t in tool_runs],
        }
    )


@bp.post("/runs/<int:run_id>/cancel")
@login_required
def cancel_run(run_id: int):
    run = services().agent_service.cancel(get_session(), g.user.id, run_id)
    return jsonify({"run": serialize_agent_run(run)})
