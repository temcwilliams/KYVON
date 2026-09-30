"""Personalisation settings: inspect, change, reset."""

from __future__ import annotations

from flask import Blueprint, g, jsonify
from sqlalchemy import select

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.schemas import SettingsUpdate
from kyvon.models import CalendarAccount
from kyvon.services.environment_context import safe_zone
from kyvon.services.settings_service import (
    UserSettings,
    get_settings,
    reset_settings,
    timezone_for,
    update_settings,
)

bp = Blueprint("settings", __name__, url_prefix="/api/v1/settings")


def _payload():
    svc = services()
    session = get_session()
    prefs = get_settings(session, g.user.id)
    data = prefs.model_dump()
    connected = session.scalar(
        select(CalendarAccount.id).where(CalendarAccount.user_id == g.user.id)
    )
    return {
        "settings": data,
        "defaults": UserSettings().model_dump(),
        "effective_timezone": str(
            safe_zone(timezone_for(session, g.user.id, svc.environment_cache.get(g.user.id)))
        ),
        "integrations": {
            "calendar": {
                "available": svc.settings.calendar_configured,
                "connected": bool(connected),
            },
            "logseq": {"available": svc.logseq is not None},
            "hermes": {"available": svc.hermes is not None},
        },
    }


@bp.get("")
@login_required
def read_settings():
    return jsonify(_payload())


@bp.patch("")
@login_required
def change_settings():
    body = parse_json(SettingsUpdate)
    update_settings(get_session(), g.user.id, body.model_dump(exclude_unset=True))
    return jsonify(_payload())


@bp.post("/reset")
@login_required
def reset():
    reset_settings(get_session(), g.user.id)
    return jsonify(_payload())
