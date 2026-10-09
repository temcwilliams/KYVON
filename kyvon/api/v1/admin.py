"""Owner-only diagnostics: status, errors, usage and run history.

Administrators only (the owner of a personal install, or admin accounts on a hosted service).
Responses never include secrets:
configuration appears only as yes/no, and free text is redacted before it is stored.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from kyvon.api.deps import admin_required, get_session, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ErrorResolve
from kyvon.models import Automation, AutomationRun, User
from kyvon.services import auth_service, observability, usage_service
from kyvon.services.automation_service import serialize_run

bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


def _int(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, "invalid_request", f"{name} must be an integer.") from None


@bp.get("/status")
@admin_required
def status():
    deep = request.args.get("deep", "").lower() in ("1", "true", "yes")
    return jsonify(observability.system_status(get_session(), services(), deep=deep))


@bp.get("/errors")
@admin_required
def errors():
    raw = request.args.get("resolved")
    resolved = None if raw in (None, "") else raw.lower() in ("1", "true", "yes")
    rows = observability.list_errors(get_session(), resolved=resolved, limit=_int("limit", 50))
    return jsonify({"errors": [observability.serialize_error(e) for e in rows]})


@bp.post("/errors/<int:error_id>/resolve")
@admin_required
def resolve(error_id: int):
    note = parse_json(ErrorResolve).note if request.data else ""
    row = observability.resolve_error(get_session(), error_id, note)
    if row is None:
        raise ApiError(404, "not_found", "Error record not found.")
    return jsonify({"error": observability.serialize_error(row)})


@bp.get("/top-users")
@admin_required
def top_users():
    """Who is using the most (hosted mode): the cost-control view."""
    from kyvon.services import usage_service

    rows = usage_service.top_users(
        get_session(),
        days=max(1, min(_int("days", 30), 365)),
        limit=max(1, min(_int("limit", 20), 100)),
    )
    return jsonify({"users": rows})


@bp.get("/usage")
@admin_required
def usage():
    return jsonify(
        observability.usage_summary(get_session(), days=max(1, min(_int("days", 7), 90)))
    )


@bp.get("/automation-runs")
@admin_required
def automation_runs():
    rows = get_session().scalars(
        select(AutomationRun)
        .join(Automation, Automation.id == AutomationRun.automation_id)
        .where(Automation.user_id == g.user.id)
        .order_by(AutomationRun.id.desc())
        .limit(max(1, min(_int("limit", 30), 100)))
    )
    return jsonify({"runs": [serialize_run(r) for r in rows]})


def _user_row(session, user: User) -> dict:
    settings = services().settings
    summary = usage_service.summary(session, settings, user)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "email_verified": user.email_verified,
        "created_at": user.created_at.isoformat(),
        "disabled": user.disabled_at is not None,
        "plan": summary["plan"],
        "used": summary["used"],
    }


@bp.get("/users")
@admin_required
def list_users():
    """Find accounts (hosted mode): by part of an email or username, newest first."""
    session = get_session()
    query = select(User).order_by(User.id.desc()).limit(max(1, min(_int("limit", 50), 200)))
    term = (request.args.get("q") or "").strip().lower()
    if term:
        like = f"%{term[:60]}%"
        query = query.where((User.email.like(like)) | (User.username.like(like)))
    return jsonify({"users": [_user_row(session, u) for u in session.scalars(query)]})


def _target(user_id: int) -> User:
    user = get_session().get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "No such account.")
    return user


@bp.post("/users/<int:user_id>/disable")
@admin_required
def disable_user(user_id: int):
    """Suspend an account: it is signed out everywhere and cannot sign in. Data is kept."""
    user = _target(user_id)
    if user.id == g.user.id:
        raise ApiError(409, "conflict", "You cannot suspend your own account.")
    session = get_session()
    if user.is_admin:
        other_admins = session.scalar(
            select(User.id).where(
                User.role == "admin", User.disabled_at.is_(None), User.id != user.id
            )
        )
        if other_admins is None:
            raise ApiError(409, "conflict", "That is the last active administrator.")
    from kyvon.db import utcnow

    user.disabled_at = utcnow()
    session.commit()
    auth_service.revoke_all_tokens(session, user.id)
    return jsonify({"user": _user_row(session, user)})


@bp.post("/users/<int:user_id>/enable")
@admin_required
def enable_user(user_id: int):
    user = _target(user_id)
    user.disabled_at = None
    get_session().commit()
    return jsonify({"user": _user_row(get_session(), user)})
