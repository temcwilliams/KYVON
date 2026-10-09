"""Due-date handling for tasks: parsing, time zones, recurrence."""

from __future__ import annotations

import calendar as _calendar
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from kyvon.services.errors import ValidationFailure

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_due(text: str, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Parse an ISO 8601 date or date-time. Returns (UTC datetime, has_time).

    * ``2026-10-03``            -> a date-only due date (start of that day in ``tz``)
    * ``2026-10-03T14:00``      -> 2 PM in ``tz``
    * ``2026-10-03T14:00-05:00``-> that exact instant
    """
    value = (text or "").strip()
    try:
        if _DATE_ONLY.match(value):
            local = datetime.combine(date.fromisoformat(value), time.min, tzinfo=tz)
            return local.astimezone(UTC), False
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationFailure(
            "Dates must look like 2026-10-03 or 2026-10-03T14:00 (ISO 8601)."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(UTC), True


def to_local_iso(due_at: datetime | None, has_time: bool, tz: ZoneInfo) -> str | None:
    if due_at is None:
        return None
    local = due_at.astimezone(tz)
    return local.isoformat() if has_time else local.date().isoformat()


def is_overdue(due_at: datetime | None, has_time: bool, now: datetime, tz: ZoneInfo) -> bool:
    if due_at is None:
        return False
    if has_time:
        return due_at < now
    return due_at.astimezone(tz).date() < now.astimezone(tz).date()


def _add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year, month = value.year + index // 12, index % 12 + 1
    day = min(value.day, _calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def next_occurrence(due_at: datetime, frequency: str, interval: int, tz: ZoneInfo) -> datetime:
    """The next due date, keeping the local wall-clock time (so 9 AM stays 9 AM across DST)."""
    local = due_at.astimezone(tz)
    if frequency == "daily":
        nxt = local + timedelta(days=interval)
    elif frequency == "weekly":
        nxt = local + timedelta(weeks=interval)
    elif frequency == "monthly":
        nxt = _add_months(local, interval)
    elif frequency == "yearly":
        nxt = _add_months(local, 12 * interval)
    else:
        raise ValidationFailure("Unknown recurrence.")
    # Re-anchor the wall clock (timedelta on aware datetimes keeps the offset, not the clock).
    nxt = datetime.combine(nxt.date(), local.time(), tzinfo=tz)
    return nxt.astimezone(UTC)
