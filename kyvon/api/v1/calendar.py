"""Google Calendar: connection (OAuth) and events."""

from __future__ import annotations

from urllib.parse import urlencode

from flask import Blueprint, g, jsonify, redirect, request

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import CalendarEventCreate, CalendarEventUpdate
from kyvon.services.calendar_service import CalendarService, complete_authorization
from kyvon.services.errors import IntegrationError, NotConnectedError, ValidationFailure

bp = Blueprint("calendar", __name__, url_prefix="/api/v1/calendar")


def _service() -> CalendarService:
    svc = services()
    return CalendarService(get_session(), g.user.id, settings=svc.settings, http=svc.http)


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, "invalid_request", f"{name} must be an integer.") from None


@bp.get("/status")
@login_required
def status():
    return jsonify(_service().status())


@bp.post("/connect")
@login_required
def connect():
    return jsonify({"authorization_url": _service().begin_authorization()})


@bp.get("/callback")
def callback():
    """Google redirects the browser here. There is no session cookie on this cross-site
    navigation (cookies are SameSite=Strict), so the user is identified by the one-time
    ``state`` created in ``connect``."""
    svc = services()
    if request.args.get("error"):
        return redirect("/?" + urlencode({"calendar": "error", "reason": "access_denied"}))
    try:
        complete_authorization(
            get_session(),
            svc.settings,
            svc.http,
            request.args.get("state", ""),
            request.args.get("code", ""),
        )
    except (ValidationFailure, NotConnectedError, IntegrationError) as problem:
        svc.error_log.log("Calendar OAuth Error", str(problem), "")
        return redirect("/?" + urlencode({"calendar": "error", "reason": str(problem)[:120]}))
    return redirect("/?calendar=connected")


@bp.post("/disconnect")
@login_required
def disconnect():
    return jsonify({"disconnected": _service().disconnect()})


@bp.get("/calendars")
@login_required
def calendars():
    return jsonify({"calendars": _service().list_calendars()})


@bp.get("/events")
@login_required
def list_events():
    events = _service().list_events(
        request.args.get("start") or None,
        request.args.get("end") or None,
        calendar_id=request.args.get("calendar_id") or None,
        query=request.args.get("q") or None,
        max_results=_int_arg("limit", 25),
    )
    return jsonify({"events": events})


@bp.post("/events")
@login_required
def create_event():
    body = parse_json(CalendarEventCreate)
    event = _service().create_event(
        body.title,
        body.start,
        body.end,
        all_day=body.all_day,
        location=body.location,
        description=body.description,
        calendar_id=body.calendar_id,
    )
    return jsonify({"event": event}), 201


@bp.get("/events/<string:event_id>")
@login_required
def get_event(event_id: str):
    return jsonify(
        {"event": _service().get_event(event_id, request.args.get("calendar_id") or None)}
    )


@bp.patch("/events/<string:event_id>")
@login_required
def update_event(event_id: str):
    body = parse_json(CalendarEventUpdate)
    event = _service().update_event(
        event_id,
        title=body.title,
        start=body.start,
        end=body.end,
        location=body.location,
        description=body.description,
        calendar_id=request.args.get("calendar_id") or None,
    )
    return jsonify({"event": event})


@bp.delete("/events/<string:event_id>")
@login_required
def delete_event(event_id: str):
    _service().delete_event(event_id, request.args.get("calendar_id") or None)
    return jsonify({"ok": True})
