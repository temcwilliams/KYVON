"""Tests for the migrated location/weather code. No live network access."""

import pytest
import requests

from kyvon.integrations import geocode_nominatim, weather_openmeteo
from kyvon.services.environment_service import EnvironmentService
from kyvon.utils.error_log import ErrorLog


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        return self.payload


class RecordingGet:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


WEATHER_PAYLOAD = {
    "timezone": "America/Chicago",
    "current": {
        "temperature_2m": 70.5,
        "apparent_temperature": 71.0,
        "relative_humidity_2m": 40,
        "precipitation": 0.0,
        "wind_speed_10m": 5.0,
        "weather_code": 2,
        "time": "2026-01-01T12:00",
    },
}


# ------------------------------------------------------------ Nominatim


def test_reverse_geocode_request_shape():
    get = RecordingGet(FakeResponse({"address": {"city": "Austin"}}))
    geocode_nominatim.reverse_geocode(30.1, -97.2, http_get=get)
    ((url, kwargs),) = get.calls
    assert url == "https://nominatim.openstreetmap.org/reverse"
    assert kwargs["params"] == {"lat": 30.1, "lon": -97.2, "format": "json", "zoom": 10}
    assert kwargs["headers"] == {"User-Agent": "KYVON-Personal-Assistant"}
    assert kwargs["timeout"] == 10


@pytest.mark.parametrize(
    ("address", "city"),
    [
        ({"city": "C", "town": "T", "village": "V", "municipality": "M"}, "C"),
        ({"town": "T", "village": "V", "municipality": "M"}, "T"),
        ({"village": "V", "municipality": "M"}, "V"),
        ({"municipality": "M"}, "M"),
        ({}, "Unknown"),
    ],
)
def test_city_fallback_order(address, city):
    result = geocode_nominatim.reverse_geocode(
        0, 0, http_get=RecordingGet(FakeResponse({"address": address}))
    )
    assert result["city"] == city


def test_display_skips_empty_parts():
    payload = {"address": {"town": "Testville", "country": "USA"}}
    result = geocode_nominatim.reverse_geocode(0, 0, http_get=RecordingGet(FakeResponse(payload)))
    assert result == {
        "city": "Testville",
        "state": "",
        "country": "USA",
        "display": "Testville, USA",
    }


def test_missing_address_key():
    result = geocode_nominatim.reverse_geocode(0, 0, http_get=RecordingGet(FakeResponse({})))
    assert result["display"] == "Unknown"


def test_geocode_http_error_raises():
    with pytest.raises(requests.HTTPError):
        geocode_nominatim.reverse_geocode(0, 0, http_get=RecordingGet(FakeResponse({}, status=500)))


# ------------------------------------------------------------ Open-Meteo


def test_weather_request_shape():
    get = RecordingGet(FakeResponse(WEATHER_PAYLOAD))
    weather_openmeteo.fetch_current_weather(30.1, -97.2, http_get=get)
    ((url, kwargs),) = get.calls
    assert url == "https://api.open-meteo.com/v1/forecast"
    assert kwargs["params"] == {
        "latitude": 30.1,
        "longitude": -97.2,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
    }
    assert kwargs["timeout"] == 10


def test_weather_result_mapping():
    result = weather_openmeteo.fetch_current_weather(
        0, 0, http_get=RecordingGet(FakeResponse(WEATHER_PAYLOAD))
    )
    assert result == {
        "temperature": 70.5,
        "feels_like": 71.0,
        "humidity": 40,
        "precipitation": 0.0,
        "wind": 5.0,
        "condition": "Partly cloudy",
        "time": "2026-01-01T12:00",
        "timezone": "America/Chicago",
    }


@pytest.mark.parametrize(
    ("code", "text"),
    [(0, "Clear sky"), (45, "Fog"), (65, "Heavy rain"), (99, "Thunderstorm with heavy hail")],
)
def test_known_weather_codes(code, text):
    payload = {"current": {"weather_code": code}, "timezone": "UTC"}
    result = weather_openmeteo.fetch_current_weather(
        0, 0, http_get=RecordingGet(FakeResponse(payload))
    )
    assert result["condition"] == text


@pytest.mark.parametrize("payload", [{"current": {"weather_code": 77}}, {"current": {}}, {}])
def test_unknown_or_missing_weather_code(payload):
    result = weather_openmeteo.fetch_current_weather(
        0, 0, http_get=RecordingGet(FakeResponse(payload))
    )
    assert result["condition"] == "Unknown conditions"


def test_weather_http_error_raises():
    with pytest.raises(requests.HTTPError):
        weather_openmeteo.fetch_current_weather(
            0, 0, http_get=RecordingGet(FakeResponse({}, status=503))
        )


# ------------------------------------------------------------ service


@pytest.fixture
def error_log(tmp_path):
    return ErrorLog(tmp_path / "data" / "kyvon_errors.log")


def boom(*_args):
    raise RuntimeError("down")


def test_service_combines_location_and_weather(error_log):
    service = EnvironmentService(
        error_log,
        geocoder=lambda lat, lon: {"display": f"{lat},{lon}"},
        weather_source=lambda lat, lon: {"condition": "Clear sky"},
    )
    assert service.get_environment(1.5, 2.5) == {
        "location": {"display": "1.5,2.5"},
        "weather": {"condition": "Clear sky"},
    }


def test_location_failure_degrades_and_logs(error_log):
    service = EnvironmentService(error_log, geocoder=boom, weather_source=lambda *_: {})
    assert service.get_location(1, 2) == {
        "city": "Unknown",
        "state": "",
        "country": "",
        "display": "Unknown location",
    }
    assert "TYPE: Location Error" in error_log.path.read_text()


def test_location_failure_does_not_block_weather(error_log):
    service = EnvironmentService(error_log, geocoder=boom, weather_source=lambda *_: {"w": 1})
    env = service.get_environment(1, 2)
    assert env["location"]["display"] == "Unknown location"
    assert env["weather"] == {"w": 1}


def test_weather_failure_logged_and_reraised(error_log):
    service = EnvironmentService(error_log, geocoder=lambda *_: {}, weather_source=boom)
    with pytest.raises(RuntimeError, match="down"):
        service.get_weather(1, 2)
    assert "TYPE: Weather Error" in error_log.path.read_text()


def test_environment_propagates_weather_failure(error_log):
    service = EnvironmentService(error_log, geocoder=lambda *_: {}, weather_source=boom)
    with pytest.raises(RuntimeError):
        service.get_environment(1, 2)


def test_unknown_location_placeholder_is_not_shared(error_log):
    service = EnvironmentService(error_log, geocoder=boom)
    service.get_location(0, 0)["city"] = "mutated"
    assert service.get_location(0, 0)["city"] == "Unknown"


# ------------------------------------------------------------ error log


def test_error_log_format(tmp_path):
    from datetime import datetime

    log = ErrorLog(tmp_path / "e.log", now=lambda: datetime(2026, 1, 2, 3, 4, 5))
    log.log("Some Error", "msg", "trace")
    assert (tmp_path / "e.log").read_text() == (
        "\n"
        + "=" * 70
        + "\nTIME: 2026-01-02T03:04:05\nTYPE: Some Error\nMESSAGE: msg\nDETAILS:\ntrace\n"
    )


def test_error_log_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    ErrorLog(blocker / "sub" / "e.log").log("t", "m")  # parent is a file -> swallowed


# ------------------------------------------------------------ parity with app.py


def test_matches_legacy_app_results(prototype, monkeypatch, tmp_path):
    """Same fake HTTP responses -> identical output from app.py and the new service."""

    def fake_get(url, **kwargs):
        if "nominatim" in url:
            return FakeResponse({"address": {"village": "Smallville", "state": "KS"}})
        return FakeResponse(WEATHER_PAYLOAD)

    monkeypatch.setattr(prototype.requests, "get", fake_get)
    legacy = {
        "location": prototype.get_location(1, 2),
        "weather": prototype.get_weather(1, 2),
    }

    service = EnvironmentService(
        ErrorLog(tmp_path / "x.log"),
        geocoder=lambda lat, lon: geocode_nominatim.reverse_geocode(lat, lon, http_get=fake_get),
        weather_source=lambda lat, lon: weather_openmeteo.fetch_current_weather(
            lat, lon, http_get=fake_get
        ),
    )
    assert service.get_environment(1, 2) == legacy
