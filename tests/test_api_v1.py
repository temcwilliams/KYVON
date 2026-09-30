"""API behavior tests for /api/v1 (ported from the prototype's characterization tests)."""

import pytest

from kyvon.services.environment_service import EnvironmentService
from kyvon.utils.error_log import ErrorLog
from tests.conftest import make_app

LOCATION = {"city": "Testville", "state": "TX", "country": "USA", "display": "Testville, TX, USA"}
WEATHER = {"condition": "Partly cloudy", "temperature": 70.5, "timezone": "America/Chicago"}


@pytest.fixture
def env_service(settings):
    return EnvironmentService(
        ErrorLog(settings.error_log),
        geocoder=lambda lat, lon: dict(LOCATION),
        weather_source=lambda lat, lon: dict(WEATHER),
    )


@pytest.fixture
def app(settings, fake_llm, env_service):
    return make_app(settings, llm=fake_llm, environment=env_service)


def post(client, message=None, **extra):
    body = dict(extra)
    if message is not None:
        body["message"] = message
    return client.post("/api/v1/chat", json=body)


# ---------------------------------------------------------------- health / errors


def test_health(client):
    assert client.get("/api/v1/health").get_json() == {"status": "ok"}


def test_unknown_route_is_json_error(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_wrong_method_is_json_error(client):
    assert client.get("/api/v1/chat").status_code == 405


# ---------------------------------------------------------------- chat validation


def test_chat_requires_json_object(client):
    response = client.post("/api/v1/chat", data="x", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_chat_requires_message(client):
    response = post(client)
    assert response.status_code == 400
    assert "message" in response.get_json()["error"]["message"]


def test_chat_rejects_blank_message(client):
    response = post(client, "   ")
    assert response.status_code == 400
    assert response.get_json()["error"]["message"] == "Empty message."


def test_chat_non_string_message_is_400(client):
    # The prototype returned 500 here; validation now rejects it properly.
    assert post(client, 5).status_code == 400


def test_chat_rejects_oversized_message(client):
    assert post(client, "x" * 10_001).status_code == 400


# ---------------------------------------------------------------- chat behavior


def test_plain_chat(client, fake_llm, settings):
    response = post(client, "hello")
    assert response.status_code == 200
    assert response.get_json() == {"response": "fake reply"}
    (call,) = fake_llm.calls
    assert call["model"] == settings.model


def test_environment_text_passed_through(client, fake_llm):
    post(client, "hi", environment="CURRENT LOCATION: Testville")
    assert "CURRENT LOCATION: Testville" in fake_llm.calls[0]["messages"][0]["content"]


def test_remember_flow_end_to_end(client, fake_llm):
    response = post(client, "remember my dog is Rex")
    assert response.get_json() == {
        "response": "Understood. I have saved that to my memory.",
        "memory_saved": True,
    }
    assert fake_llm.calls == []
    memories = client.get("/api/v1/memories").get_json()["memories"]
    assert [m["memory"] for m in memories] == ["my dog is Rex"]

    post(client, "hi")
    assert "- my dog is Rex" in fake_llm.calls[0]["messages"][0]["content"]


def test_web_search(client, fake_llm, settings):
    assert post(client, "web python release").get_json() == {"response": "fake reply", "web": True}
    assert fake_llm.calls[0]["model"] == settings.web_model


def test_llm_failure_is_500_and_logged(client, fake_llm, settings):
    fake_llm.error = RuntimeError("boom")
    response = post(client, "hi")
    assert response.status_code == 500
    assert response.get_json()["error"] == {"code": "chat_failed", "message": "boom"}
    assert "Chat Error" in settings.error_log.read_text()


# ---------------------------------------------------------------- environment


def test_environment_endpoint(client):
    response = client.post("/api/v1/environment", json={"latitude": 1, "longitude": 2})
    assert response.status_code == 200
    assert response.get_json() == {"location": LOCATION, "weather": WEATHER}


@pytest.mark.parametrize(
    "body", [{"latitude": "x", "longitude": 1}, {"latitude": 1}, {"latitude": 91, "longitude": 0}]
)
def test_environment_bad_input_is_400(client, body):
    assert client.post("/api/v1/environment", json=body).status_code == 400


def test_environment_weather_failure_is_500(app, client, settings):
    def boom(lat, lon):
        raise RuntimeError("down")

    app.extensions["kyvon"].environment = EnvironmentService(
        ErrorLog(settings.error_log), geocoder=lambda *_: {}, weather_source=boom
    )
    response = client.post("/api/v1/environment", json={"latitude": 1, "longitude": 2})
    assert response.status_code == 500
    assert response.get_json()["error"]["message"] == "down"
    assert "Environment Error" in settings.error_log.read_text()


# ---------------------------------------------------------------- status


def test_status_is_cheap_by_default(client, fake_llm):
    body = client.get("/api/v1/status").get_json()
    assert body["online"] is True
    assert [d["name"] for d in body["diagnostics"]] == ["Python", "Memory", "Groq AI"]
    assert fake_llm.calls == []


def test_deep_status_calls_model(client, fake_llm):
    fake_llm.reply = "ONLINE"
    body = client.get("/api/v1/status?deep=1").get_json()
    assert body["diagnostics"][-1] == {"name": "Groq AI", "status": "ONLINE", "details": "ONLINE"}
    assert len(fake_llm.calls) == 1
    assert fake_llm.calls[0]["temperature"] == 0 and fake_llm.calls[0]["max_tokens"] == 10


def test_deep_status_reports_llm_error(client, fake_llm):
    fake_llm.error = RuntimeError("no groq")
    body = client.get("/api/v1/status?deep=1").get_json()
    assert body["online"] is False
    assert body["diagnostics"][-1]["details"] == "no groq"


# ---------------------------------------------------------------- web client


def test_index_page_served(anon_client):
    response = anon_client.get("/")
    assert response.status_code == 200
    assert b"<title>KYVON</title>" in response.data
    assert b"J.A.R.V.I.S" not in response.data
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "path",
    [
        "css/style.css",
        "js/main.js",
        "js/api.js",
        "js/auth.js",
        "js/chat.js",
        "js/env.js",
        "js/memory.js",
        "js/diagnostics.js",
        "js/voice.js",
        "js/ui.js",
    ],
)
def test_static_assets_served(anon_client, path):
    assert anon_client.get(f"/static/{path}").status_code == 200


def test_index_references_only_existing_assets(anon_client):
    import re

    html = anon_client.get("/").get_data(as_text=True)
    for asset in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
        assert anon_client.get(asset).status_code == 200, asset


def test_page_has_no_inline_script_or_handlers(anon_client):
    html = anon_client.get("/").get_data(as_text=True)
    assert " onclick=" not in html
    assert "<script>" not in html
