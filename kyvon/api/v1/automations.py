"""Automations (reminders and scheduled tasks) and the notification inbox."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import AutomationCreate, AutomationUpdate
from kyvon.services.automation_service import (
    AutomationService,
    serialize_automation,
    serialize_run,
)
from kyvon.services.notification_service import NotificationService, serialize_notification

bp = Blueprint("automations", __name__, url_prefix="/api/v1")


def _automations() -> AutomationService:
    return AutomationService(
        get_session(), g.user.id, max_automations=services().settings.automation_max_per_user
    )


def _notes() -> NotificationService:
    return NotificationService(get_session(), g.user.id)


@bp.get("/automations")
@login_required
def list_automations():
    return jsonify({"automations": [serialize_automation(a) for a in _automations().list()]})


@bp.post("/automations")
@login_required
def create_automation():
    body = parse_json(AutomationCreate)
    automation = _automations().create(
        body.name,
        body.kind,
        body.schedule,
        text=body.text,
        prompt=body.prompt,
        timezone=body.timezone,
    )
    return jsonify({"automation": serialize_automation(automation)}), 201


@bp.get("/automations/<int:automation_id>")
@login_required
def get_automation(automation_id: int):
    return jsonify({"automation": serialize_automation(_automations().get(automation_id))})


@bp.patch("/automations/<int:automation_id>")
@login_required
def update_automation(automation_id: int):
    body = parse_json(AutomationUpdate)
    automation = _automations().update(
        automation_id,
        name=body.name,
        schedule=body.schedule,
        text=body.text,
        prompt=body.prompt,
        enabled=body.enabled,
    )
    return jsonify({"automation": serialize_automation(automation)})


@bp.delete("/automations/<int:automation_id>")
@login_required
def delete_automation(automation_id: int):
    _automations().delete(automation_id)
    return jsonify({"ok": True})


@bp.post("/automations/<int:automation_id>/run")
@login_required
def run_automation(automation_id: int):
    _automations().get(automation_id)  # ownership check
    services().scheduler.run_now(automation_id)
    return jsonify({"started": True}), 202


@bp.get("/automations/<int:automation_id>/runs")
@login_required
def automation_runs(automation_id: int):
    rows = _automations().runs(automation_id)
    return jsonify({"runs": [serialize_run(r) for r in rows]})


# ------------------------------------------------------------------ notifications


@bp.get("/notifications")
@login_required
def list_notifications():
    unread = request.args.get("unread", "").lower() in ("1", "true", "yes")
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        raise ApiError(400, "invalid_request", "limit must be an integer.") from None
    notes = _notes()
    return jsonify(
        {
            "notifications": [
                serialize_notification(n) for n in notes.list(unread_only=unread, limit=limit)
            ],
            "unread_count": notes.unread_count(),
        }
    )


@bp.post("/notifications/read-all")
@login_required
def read_all():
    return jsonify({"marked": _notes().mark_all_read()})


@bp.post("/notifications/<int:note_id>/read")
@login_required
def mark_read(note_id: int):
    return jsonify({"notification": serialize_notification(_notes().mark_read(note_id))})


@bp.delete("/notifications/<int:note_id>")
@login_required
def delete_notification(note_id: int):
    _notes().delete(note_id)
    return jsonify({"ok": True})
