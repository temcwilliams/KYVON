"""Per-user settings (structured, validated). Extended in Phase 10; the time zone helper
is needed earlier by the time tool and the environment context."""

from __future__ import annotations

from sqlalchemy.orm import Session

from kyvon.models import User
from kyvon.services.environment_context import safe_zone


def timezone_for(session: Session, user_id: int, cached_environment: dict | None = None) -> str:
    """The user's time zone: their saved setting, else the last known location's, else UTC."""
    user = session.get(User, user_id)
    saved = ((user.settings or {}) if user else {}).get("timezone")
    if saved:
        return str(safe_zone(saved))
    zone = ((cached_environment or {}).get("weather") or {}).get("timezone")
    return str(safe_zone(zone)) if zone else "UTC"
