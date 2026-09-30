"""Temporary context: current time, location and weather.

This is rebuilt per request and never stored in the database. The last known
location per user is cached in memory for a short time, so the browser does not
need to send prompt text with every message.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kyvon.llm.prompts import DEFAULT_ENVIRONMENT

CACHE_TTL_SECONDS = 15 * 60


def safe_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_celsius(fahrenheit):
    return None if fahrenheit is None else round((fahrenheit - 32) * 5 / 9, 1)


def kmh(mph):
    return None if mph is None else round(mph * 1.609344, 1)


def mm(inches):
    return None if inches is None else round(inches * 25.4, 1)


class EnvironmentCache:
    def __init__(self, *, ttl: float = CACHE_TTL_SECONDS, clock: Callable[[], float] = time.time):
        self._ttl = ttl
        self._clock = clock
        self._items: dict[int, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def put(self, user_id: int, environment: dict) -> None:
        with self._lock:
            self._items[user_id] = (self._clock(), environment)

    def get(self, user_id: int) -> dict | None:
        with self._lock:
            entry = self._items.get(user_id)
            if entry is None:
                return None
            stored_at, environment = entry
            if self._clock() - stored_at > self._ttl:
                del self._items[user_id]
                return None
            return environment


def render_environment(
    environment: dict | None,
    *,
    now: datetime | None = None,
    timezone: str | None = None,
    units: str = "imperial",
) -> str:
    """Text block for the prompt: server time plus, when known, location and weather."""
    now = (now or datetime.now(UTC)).astimezone(
        safe_zone(timezone or (environment or {}).get("weather", {}).get("timezone"))
    )
    lines = [f"Current date and time: {now.strftime('%A, %B %d, %Y, %I:%M %p')} ({now.tzname()})"]

    if not environment:
        lines.append(DEFAULT_ENVIRONMENT)
        return "\n".join(lines)

    location = environment.get("location") or {}
    weather = environment.get("weather") or {}
    if location:
        lines.append(f"Location: {location.get('display', 'Unknown')}")
    if weather:
        if units == "metric":
            temp, feels = (
                to_celsius(weather.get("temperature")),
                to_celsius(weather.get("feels_like")),
            )
            temperature = f"Temperature: {temp}°C (feels like {feels}°C)"
            precipitation = f"Precipitation: {mm(weather.get('precipitation'))} mm"
            wind = f"Wind: {kmh(weather.get('wind'))} km/h"
        else:
            temperature = (
                f"Temperature: {weather.get('temperature')}°F "
                f"(feels like {weather.get('feels_like')}°F)"
            )
            precipitation = f"Precipitation: {weather.get('precipitation')} inches"
            wind = f"Wind: {weather.get('wind')} mph"
        lines += [
            f"Weather: {weather.get('condition')}",
            temperature,
            f"Humidity: {weather.get('humidity')}%",
            precipitation,
            wind,
            f"Time zone: {weather.get('timezone')}",
        ]
    return "\n".join(lines)
