"""Tasks."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import get_session, login_required, parse_json
from kyvon.api.errors import ApiError
from kyvon.api.schemas import TaskCreate, TaskUpdate
from kyvon.services.task_service import UNSET, TaskService

bp = Blueprint("tasks", __name__, url_prefix="/api/v1/tasks")


def _service() -> TaskService:
    return TaskService(get_session(), g.user.id)


def _bool_arg(name: str) -> bool | None:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw.lower() in ("1", "true", "yes")


@bp.get("")
@login_required
def list_tasks():
    service = _service()
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        raise ApiError(400, "invalid_request", "limit must be an integer.") from None
    priority = request.args.get("priority")
    rows = service.list(
        status=request.args.get("status", "open"),
        priority=int(priority) if priority and priority.isdigit() else priority or None,
        due_before=request.args.get("due_before") or None,
        due_after=request.args.get("due_after") or None,
        overdue=_bool_arg("overdue"),
        query=request.args.get("q") or None,
        limit=limit,
    )
    return jsonify(
        {"tasks": [service.serialize(t) for t in rows], "open_count": service.count_open()}
    )


@bp.post("")
@login_required
def create_task():
    body = parse_json(TaskCreate)
    service = _service()
    task = service.create(
        body.title,
        notes=body.notes,
        priority=body.priority,
        due=body.due,
        recurrence=body.recurrence,
        recurrence_interval=body.recurrence_interval,
    )
    return jsonify({"task": service.serialize(task)}), 201


@bp.get("/<int:task_id>")
@login_required
def get_task(task_id: int):
    service = _service()
    return jsonify({"task": service.serialize(service.get(task_id))})


@bp.patch("/<int:task_id>")
@login_required
def update_task(task_id: int):
    body = parse_json(TaskUpdate)
    given = body.model_fields_set
    service = _service()
    task = service.update(
        task_id,
        **{
            name: (getattr(body, name) if name in given else UNSET)
            for name in (
                "title",
                "notes",
                "priority",
                "due",
                "recurrence",
                "recurrence_interval",
            )
        },
    )
    return jsonify({"task": service.serialize(task)})


@bp.post("/<int:task_id>/complete")
@login_required
def complete_task(task_id: int):
    service = _service()
    task, follow_up = service.complete(task_id)
    return jsonify(
        {
            "task": service.serialize(task),
            "next_task": service.serialize(follow_up) if follow_up else None,
        }
    )


@bp.post("/<int:task_id>/reopen")
@login_required
def reopen_task(task_id: int):
    service = _service()
    return jsonify({"task": service.serialize(service.reopen(task_id))})


@bp.delete("/<int:task_id>")
@login_required
def delete_task(task_id: int):
    _service().delete(task_id)
    return jsonify({"ok": True})
