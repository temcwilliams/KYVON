"""Owner-only diagnostics: status, errors, usage and run history.

KYVON is single-owner, so "signed in" is the admin check. Responses never include secrets:
configuration appears only as yes/no, and free text is redacted before it is stored.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ErrorResolve
from kyvon.models import Automation, AutomationRun
from kyvon.services import observability
from kyvon.services.automation_service import serialize_run

bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


def _int(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, "invalid_request", f"{name} must be an integer.") from None


@bp.get("/status")
@login_required
def status():
    deep = request.args.get("deep", "").lower() in ("1", "true", "yes")
    return jsonify(observability.system_status(get_session(), services(), deep=deep))


@bp.get("/errors")
@login_required
def errors():
    raw = request.args.get("resolved")
    resolved = None if raw in (None, "") else raw.lower() in ("1", "true", "yes")
    rows = observability.list_errors(get_session(), resolved=resolved, limit=_int("limit", 50))
    return jsonify({"errors": [observability.serialize_error(e) for e in rows]})


@bp.post("/errors/<int:error_id>/resolve")
@login_required
def resolve(error_id: int):
    note = parse_json(ErrorResolve).note if request.data else ""
    row = observability.resolve_error(get_session(), error_id, note)
    if row is None:
        raise ApiError(404, "not_found", "Error record not found.")
    return jsonify({"error": observability.serialize_error(row)})


@bp.get("/usage")
@login_required
def usage():
    return jsonify(
        observability.usage_summary(get_session(), days=max(1, min(_int("days", 7), 90)))
    )


@bp.get("/automation-runs")
@login_required
def automation_runs():
    rows = get_session().scalars(
        select(AutomationRun)
        .join(Automation, Automation.id == AutomationRun.automation_id)
        .where(Automation.user_id == g.user.id)
        .order_by(AutomationRun.id.desc())
        .limit(max(1, min(_int("limit", 30), 100)))
    )
    return jsonify({"runs": [serialize_run(r) for r in rows]})
