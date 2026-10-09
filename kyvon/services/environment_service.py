"""Location + weather lookup for a coordinate pair.

Failure semantics match the prototype: a failed reverse-geocode degrades to an
"Unknown location" placeholder, while a failed weather lookup is logged and
re-raised so the caller can return an error.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable

from kyvon.integrations import geocode_nominatim, weather_openmeteo
from kyvon.utils.error_log import ErrorLog

UNKNOWN_LOCATION = {
    "city": "Unknown",
    "state": "",
    "country": "",
    "display": "Unknown location",
}


class EnvironmentService:
    def __init__(
        self,
        error_log: ErrorLog,
        *,
        geocoder: Callable[[float, float], dict] = geocode_nominatim.reverse_geocode,
        weather_source: Callable[[float, float], dict] = weather_openmeteo.fetch_current_weather,
    ):
        self._error_log = error_log
        self._geocoder = geocoder
        self._weather_source = weather_source

    def get_location(self, latitude: float, longitude: float) -> dict:
        try:
            return self._geocoder(latitude, longitude)
        except Exception as error:
            self._error_log.log("Location Error", str(error), traceback.format_exc())
            return dict(UNKNOWN_LOCATION)

    def get_weather(self, latitude: float, longitude: float) -> dict:
        try:
            return self._weather_source(latitude, longitude)
        except Exception as error:
            self._error_log.log("Weather Error", str(error), traceback.format_exc())
            raise

    def get_environment(self, latitude: float, longitude: float) -> dict:
        """Location first, then weather (as the prototype's route does)."""
        location = self.get_location(latitude, longitude)
        weather = self.get_weather(latitude, longitude)
        return {"location": location, "weather": weather}
