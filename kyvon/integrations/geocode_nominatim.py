"""Reverse geocoding via OpenStreetMap Nominatim."""

from __future__ import annotations

from collections.abc import Callable

import requests

URL = "https://nominatim.openstreetmap.org/reverse"
# Nominatim's usage policy requires an identifying User-Agent.
USER_AGENT = "KYVON-Personal-Assistant"
TIMEOUT_SECONDS = 10


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    http_get: Callable[..., requests.Response] = requests.get,
) -> dict:
    """Return ``{"city", "state", "country", "display"}``. Raises on any failure."""
    response = http_get(
        URL,
        params={"lat": latitude, "lon": longitude, "format": "json", "zoom": 10},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    address = response.json().get("address", {})

    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or "Unknown"
    )
    state = address.get("state") or ""
    country = address.get("country") or ""

    return {
        "city": city,
        "state": state,
        "country": country,
        "display": ", ".join(part for part in [city, state, country] if part),
    }


SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def forward_geocode(
    query: str,
    *,
    http_get: Callable[..., requests.Response] = requests.get,
) -> dict | None:
    """Look up a place name. Returns ``{"latitude", "longitude", "display"}`` or None."""
    response = http_get(
        SEARCH_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    first = results[0]
    return {
        "latitude": float(first["lat"]),
        "longitude": float(first["lon"]),
        "display": first.get("display_name", query),
    }
