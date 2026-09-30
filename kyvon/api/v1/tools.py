"""Tool catalogue, the audit trail, and confirmation of pending actions."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from kyvon.api.deps import get_session, login_required, services
from kyvon.api.errors import ApiError
from kyvon.models import ToolRun
from kyvon.services.errors import NotFoundError
from kyvon.tools.executor import serialize_tool_run

bp = Blueprint("tools", __name__, url_prefix="/api/v1")


@bp.get("/tools")
@login_required
def list_tools():
    svc = services()
    return jsonify(
        {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "risk": t.risk.value,
                    "requires_confirmation": t.requires_confirmation,
                    "parameters": t.spec()["function"]["parameters"],
                }
                for t in svc.registry.available(svc)
            ]
        }
    )


@bp.get("/tool-runs")
@login_required
def list_runs():
    session = get_session()
    services().executor.expire_stale(session, g.user.id)
    query = select(ToolRun).where(ToolRun.user_id == g.user.id)
    if request.args.get("status"):
        query = query.where(ToolRun.status == request.args["status"])
    if request.args.get("tool"):
        query = query.where(ToolRun.tool_name == request.args["tool"])
    if request.args.get("conversation_id"):
        try:
            query = query.where(ToolRun.conversation_id == int(request.args["conversation_id"]))
        except ValueError:
            raise ApiError(400, "invalid_request", "conversation_id must be an integer.") from None
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        raise ApiError(400, "invalid_request", "limit must be an integer.") from None
    rows = session.scalars(query.order_by(ToolRun.id.desc()).limit(limit))
    return jsonify({"tool_runs": [serialize_tool_run(r) for r in rows]})


@bp.get("/tool-runs/pending")
@login_required
def pending_runs():
    session = get_session()
    services().executor.expire_stale(session, g.user.id)
    rows = session.scalars(
        select(ToolRun)
        .where(ToolRun.user_id == g.user.id, ToolRun.status == "pending_confirmation")
        .order_by(ToolRun.id.desc())
    )
    return jsonify({"tool_runs": [serialize_tool_run(r) for r in rows]})


@bp.get("/tool-runs/<int:run_id>")
@login_required
def get_run(run_id: int):
    run = get_session().scalar(
        select(ToolRun).where(ToolRun.id == run_id, ToolRun.user_id == g.user.id)
    )
    if run is None:
        raise NotFoundError("Action not found.")
    return jsonify({"tool_run": serialize_tool_run(run)})


@bp.post("/tool-runs/<int:run_id>/confirm")
@login_required
def confirm_run(run_id: int):
    run = services().executor.confirm(get_session(), g.user.id, run_id)
    return jsonify({"tool_run": serialize_tool_run(run)})


@bp.post("/tool-runs/<int:run_id>/reject")
@login_required
def reject_run(run_id: int):
    run = services().executor.reject(get_session(), g.user.id, run_id)
    return jsonify({"tool_run": serialize_tool_run(run)})
