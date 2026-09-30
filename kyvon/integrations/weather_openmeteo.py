"""Current weather via Open-Meteo (no API key required)."""

from __future__ import annotations

from collections.abc import Callable

import requests

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10

CURRENT_FIELDS = (
    "temperature_2m,"
    "relative_humidity_2m,"
    "apparent_temperature,"
    "precipitation,"
    "weather_code,"
    "wind_speed_10m"
)

# Same table as the prototype (some WMO codes are intentionally still missing).
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def fetch_current_weather(
    latitude: float,
    longitude: float,
    *,
    http_get: Callable[..., requests.Response] = requests.get,
) -> dict:
    """Return current conditions in °F / mph. Raises on any failure."""
    response = http_get(
        URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": CURRENT_FIELDS,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    data = response.json()
    current = data.get("current", {})

    return {
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "precipitation": current.get("precipitation"),
        "wind": current.get("wind_speed_10m"),
        "condition": WEATHER_CODES.get(current.get("weather_code"), "Unknown conditions"),
        "time": current.get("time"),
        "timezone": data.get("timezone"),
    }
