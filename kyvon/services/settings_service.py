"""Per-user settings: structured, validated, and small.

Personalisation is kept as data, not prose: these settings are turned into a few short
lines of context per request (see ``render_profile``) instead of a giant system prompt.
Nothing sensitive is stored here: no credentials, and free-text fields are checked for
secrets. Settings the assistant itself may change are limited (and need approval); the
free-text ``assistant_notes`` can only be edited by the user.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from kyvon.models import User
from kyvon.services.environment_context import safe_zone
from kyvon.services.errors import ValidationFailure
from kyvon.services.memory_rules import looks_like_secret

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _zone(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("is not a valid time zone (use a name like America/Chicago)") from None
    return value


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    timezone: str | None = Field(
        default=None, description="Explicit time zone; overrides detection."
    )
    detected_timezone: str | None = Field(default=None, description="Reported by the device.")
    display_name: str | None = Field(default=None, max_length=60)
    response_style: Literal["concise", "balanced", "detailed"] = "balanced"
    tone: Literal["default", "warm", "formal", "playful"] = "default"
    units: Literal["imperial", "metric"] = "imperial"
    language: str = Field(default="English", min_length=1, max_length=30)
    week_starts_on: Literal["sun", "mon"] = "sun"
    assistant_notes: str = Field(default="", max_length=500)
    allow_memory_proposals: bool = True
    voice_replies: bool = False
    calendar_enabled: bool = True
    logseq_enabled: bool = True
    hermes_enabled: bool = True

    @field_validator("timezone", "detected_timezone")
    @classmethod
    def _valid_zone(cls, value):
        return _zone(value)

    @field_validator("display_name", "language", "assistant_notes")
    @classmethod
    def _plain_text(cls, value):
        if value is None:
            return value
        if _CONTROL.search(value):
            raise ValueError("contains control characters")
        if looks_like_secret(value):
            raise ValueError("looks like a password or key, which must not be stored here")
        return value

    @field_validator("display_name", "language")
    @classmethod
    def _single_line(cls, value):
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("must be a single line")
        return value

    @field_validator("display_name")
    @classmethod
    def _empty_name_means_none(cls, value):
        return value or None


# Which settings the assistant may propose changing (each needs the user's approval).
ASSISTANT_EDITABLE = (
    "display_name",
    "response_style",
    "tone",
    "units",
    "language",
    "timezone",
    "week_starts_on",
)

# Hermes is an agent, not a tool: its switch is enforced where agents are started.
INTEGRATION_TOOL_PREFIXES = {
    "calendar_enabled": "calendar_",
    "logseq_enabled": "logseq_",
}


def _stored(user: User | None) -> dict:
    return dict(user.settings or {}) if user else {}


def get_settings(session: Session, user_id: int) -> UserSettings:
    """Stored values merged over the defaults. Unknown or invalid stored keys are ignored."""
    stored = _stored(session.get(User, user_id))
    known = {k: v for k, v in stored.items() if k in UserSettings.model_fields}
    try:
        return UserSettings(**known)
    except ValidationError:
        good = {}
        for key, value in known.items():
            try:
                UserSettings(**{key: value})
                good[key] = value
            except ValidationError:
                continue
        return UserSettings(**good)


def update_settings(session: Session, user_id: int, changes: dict[str, Any]) -> UserSettings:
    """Apply a partial update. ``None`` clears optional fields; unknown keys are rejected."""
    unknown = set(changes) - set(UserSettings.model_fields)
    if unknown:
        raise ValidationFailure(f"Unknown setting: {', '.join(sorted(unknown))}.")
    current = get_settings(session, user_id).model_dump()
    merged = {**current, **changes}
    try:
        validated = UserSettings(**merged)
    except ValidationError as error:
        first = error.errors()[0]
        raise ValidationFailure(
            f"{'.'.join(str(p) for p in first['loc'])} {first['msg']}"
        ) from None
    user = session.get(User, user_id)
    user.settings = validated.model_dump()
    session.commit()
    return validated


def reset_settings(session: Session, user_id: int) -> UserSettings:
    user = session.get(User, user_id)
    user.settings = {}
    session.commit()
    return UserSettings()


def timezone_for(session: Session, user_id: int, cached_environment: dict | None = None) -> str:
    """Explicit setting, else what the device reported, else the last location's, else UTC."""
    s = get_settings(session, user_id)
    for candidate in (s.timezone, s.detected_timezone):
        if candidate:
            return str(safe_zone(candidate))
    zone = ((cached_environment or {}).get("weather") or {}).get("timezone")
    return str(safe_zone(zone)) if zone else "UTC"


def disabled_tool_prefixes(settings: UserSettings) -> tuple[str, ...]:
    return tuple(
        prefix for flag, prefix in INTEGRATION_TOOL_PREFIXES.items() if not getattr(settings, flag)
    )


def allowed_tool_names(all_names: list[str], settings: UserSettings) -> set[str]:
    """Tools this user has not switched off (by integration) and may still use."""
    blocked = disabled_tool_prefixes(settings)
    names = {n for n in all_names if not n.startswith(blocked)} if blocked else set(all_names)
    if not settings.allow_memory_proposals:
        names -= {"memory_create", "memory_update", "memory_delete"}
    return names


def render_profile(settings: UserSettings, *, connected: list[str] | None = None) -> str:
    """Short context lines. Only non-default preferences are included."""
    defaults = UserSettings()
    lines: list[str] = []
    if settings.display_name:
        lines.append(f"Their name is {settings.display_name}.")
    if settings.response_style != defaults.response_style:
        lines.append(
            {
                "concise": "They prefer short, to-the-point answers.",
                "detailed": "They prefer thorough, detailed answers.",
            }[settings.response_style]
        )
    if settings.tone != defaults.tone:
        lines.append(f"Preferred tone: {settings.tone}.")
    if settings.language != defaults.language:
        lines.append(f"Reply in {settings.language} unless asked otherwise.")
    if settings.units == "metric":
        lines.append("Use metric units (°C, km/h) rather than °F and mph.")
    if settings.week_starts_on == "mon":
        lines.append("Their week starts on Monday.")
    if settings.assistant_notes:
        lines.append(f"Their own note about how to help them: {settings.assistant_notes}")
    if connected:
        lines.append("Connected services: " + ", ".join(connected) + ".")
    return "\n".join(lines)
