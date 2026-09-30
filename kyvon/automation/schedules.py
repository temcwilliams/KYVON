"""Schedule specs and "when is the next run".

A schedule is a small validated dict, so it can be stored as JSON and edited safely:

    {"type": "once",     "at": "2026-10-03T08:00"}
    {"type": "daily",    "time": "08:00"}
    {"type": "weekly",   "days": ["mon", "sun"], "time": "18:00"}
    {"type": "monthly",  "day": 1, "time": "09:00"}          (day 29-31 clamps to month end)
    {"type": "interval", "minutes": 60}                       (minimum 15 minutes)

Times are wall-clock times in the automation's time zone, so "8 AM" stays 8 AM across DST.
The 15-minute floor and the failure auto-disable in the runner keep an automation from
becoming a runaway loop.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from kyvon.services.errors import ValidationFailure

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 60 * 24 * 7
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_time(value: str) -> time:
    match = _TIME.match((value or "").strip())
    if not match:
        raise ValidationFailure("Times must look like 08:00 (24-hour).")
    return time(int(match.group(1)), int(match.group(2)))


def validate_schedule(spec: dict, tz: ZoneInfo) -> dict:
    """Return a normalised copy of ``spec`` or raise ValidationFailure."""
    if not isinstance(spec, dict):
        raise ValidationFailure("The schedule must be an object.")
    kind = spec.get("type")
    if kind == "once":
        at = str(spec.get("at", "")).strip()
        try:
            naive = datetime.fromisoformat(at)
        except ValueError:
            raise ValidationFailure(
                "A one-time schedule needs 'at' like 2026-10-03T08:00."
            ) from None
        if naive.tzinfo is not None:  # normalise explicit offsets to the automation's zone
            naive = naive.astimezone(tz).replace(tzinfo=None)
        return {"type": "once", "at": naive.strftime("%Y-%m-%dT%H:%M")}
    if kind == "daily":
        return {"type": "daily", "time": parse_time(spec.get("time", "")).strftime("%H:%M")}
    if kind == "weekly":
        days = spec.get("days")
        if not isinstance(days, list) or not days:
            raise ValidationFailure("A weekly schedule needs 'days', e.g. ['mon', 'fri'].")
        cleaned = {str(d).strip().lower()[:3] for d in days}
        if not cleaned <= set(WEEKDAYS):
            raise ValidationFailure(f"Days must be from: {', '.join(WEEKDAYS)}.")
        ordered = [d for d in WEEKDAYS if d in cleaned]
        return {
            "type": "weekly",
            "days": ordered,
            "time": parse_time(spec.get("time", "")).strftime("%H:%M"),
        }
    if kind == "monthly":
        day = spec.get("day")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise ValidationFailure("A monthly schedule needs 'day' from 1 to 31.")
        return {
            "type": "monthly",
            "day": day,
            "time": parse_time(spec.get("time", "")).strftime("%H:%M"),
        }
    if kind == "interval":
        minutes = spec.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise ValidationFailure("An interval schedule needs whole 'minutes'.")
        if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValidationFailure(
                f"Intervals must be between {MIN_INTERVAL_MINUTES} minutes and 7 days."
            )
        return {"type": "interval", "minutes": minutes}
    raise ValidationFailure("Schedule type must be once, daily, weekly, monthly or interval.")


def _local(day, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)


def next_run(spec: dict, tz: ZoneInfo, after: datetime) -> datetime | None:
    """The first run strictly after ``after`` (UTC), or None when there is none."""
    kind = spec["type"]
    local_after = after.astimezone(tz)

    if kind == "once":
        at = datetime.fromisoformat(spec["at"]).replace(tzinfo=tz)
        return at.astimezone(UTC) if at.astimezone(UTC) > after else None

    if kind == "interval":
        return after + timedelta(minutes=spec["minutes"])

    at = parse_time(spec["time"])
    day = local_after.date()
    for offset in range(0, 366 * 2):
        candidate_day = day + timedelta(days=offset)
        if kind == "weekly" and WEEKDAYS[candidate_day.weekday()] not in spec["days"]:
            continue
        if kind == "monthly":
            last = calendar.monthrange(candidate_day.year, candidate_day.month)[1]
            if candidate_day.day != min(spec["day"], last):
                continue
        candidate = _local(candidate_day, at, tz).astimezone(UTC)
        if candidate > after:
            return candidate
    return None


def describe(spec: dict) -> str:
    kind = spec["type"]
    if kind == "once":
        return f"once at {spec['at'].replace('T', ' ')}"
    if kind == "daily":
        return f"every day at {spec['time']}"
    if kind == "weekly":
        return f"every {', '.join(spec['days'])} at {spec['time']}"
    if kind == "monthly":
        return f"on day {spec['day']} of each month at {spec['time']}"
    minutes = spec["minutes"]
    return f"every {minutes // 60} hours" if minutes % 60 == 0 else f"every {minutes} minutes"
