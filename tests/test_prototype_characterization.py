"""Characterization tests: pin the behavior of the legacy prototype (app.py).

These describe what the code does today, including known quirks, so the
refactor into the kyvon/ package cannot change behavior silently.
"""

import importlib
import json
import sys

import pytest

# ---------------------------------------------------------------- startup


def test_missing_api_key_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    sys.modules.pop("app", None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        importlib.import_module("app")
    sys.modules.pop("app", None)


def test_data_dir_created_relative_to_cwd(prototype, tmp_path):
    assert (tmp_path / "data").is_dir()


def test_models_unchanged(prototype):
    assert prototype.MODEL == "openai/gpt-oss-120b"
    assert prototype.WEB_MODEL == "groq/compound"


# ---------------------------------------------------------------- pages


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"KYVON" in response.data


# ---------------------------------------------------------------- chat validation


def test_chat_requires_message(client):
    response = client.post("/api/chat", json={})
    assert response.status_code == 400
    assert response.get_json() == {"error": "No message provided."}


def test_chat_rejects_blank_message(client):
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Empty message."}


def test_chat_non_string_message_is_500(client):
    # Known quirk: no type validation, .strip() raises.
    response = client.post("/api/chat", json={"message": 5})
    assert response.status_code == 500
    assert response.get_json()["diagnosed"] is True


# ---------------------------------------------------------------- LLM chat


def test_plain_chat_calls_main_model(client, prototype):
    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 200
    assert response.get_json() == {"response": "fake reply"}

    (call,) = prototype.completions.calls
    assert call["model"] == prototype.MODEL
    assert call["temperature"] == 0.7
    assert call["max_tokens"] == 1500
    system, user = call["messages"]
    assert system["role"] == "system" and "You are KYVON" in system["content"]
    assert user == {"role": "user", "content": "hello"}


def test_chat_is_stateless_single_user_message(client, prototype):
    client.post("/api/chat", json={"message": "first"})
    client.post("/api/chat", json={"message": "second"})
    for call in prototype.completions.calls:
        assert [m["role"] for m in call["messages"]] == ["system", "user"]


def test_environment_and_memory_injected_into_prompt(client, prototype):
    client.post("/api/chat", json={"message": "remember I like tea"})
    client.post(
        "/api/chat",
        json={"message": "hi", "environment": "CURRENT LOCATION: Testville"},
    )
    system = prototype.completions.calls[0]["messages"][0]["content"]
    assert "- I like tea" in system
    assert "CURRENT LOCATION: Testville" in system


def test_default_environment_text(client, prototype):
    client.post("/api/chat", json={"message": "hi"})
    system = prototype.completions.calls[0]["messages"][0]["content"]
    assert "No location or weather information available." in system
    assert "No saved memories." in system


def test_llm_failure_returns_500_and_logs(client, prototype, tmp_path):
    prototype.completions.error = RuntimeError("boom")
    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code == 500
    assert response.get_json() == {"error": "boom", "diagnosed": True}
    assert "Chat Error" in (tmp_path / "data" / "kyvon_errors.log").read_text()


# ---------------------------------------------------------------- memory


def test_remember_saves_without_calling_llm(client, prototype, tmp_path):
    response = client.post("/api/chat", json={"message": "remember my dog is Rex"})
    assert response.get_json() == {
        "response": "Understood. I have saved that to my memory.",
        "memory_saved": True,
    }
    assert prototype.completions.calls == []

    saved = json.loads((tmp_path / "data" / "kyvon_memory.json").read_text())
    assert [m["memory"] for m in saved] == ["my dog is Rex"]
    assert "date" in saved[0]


def test_remember_prefix_is_case_insensitive(client):
    response = client.post("/api/chat", json={"message": "REMEMBER x"})
    assert response.get_json()["memory_saved"] is True


def test_remember_that_keeps_word_that_quirk(client):
    # Known quirk: "remember " matches first, so "that" stays in the text.
    client.post("/api/chat", json={"message": "remember that I am tall"})
    memories = client.get("/api/memory").get_json()["memories"]
    assert memories[0]["memory"] == "that I am tall"


@pytest.mark.parametrize("phrase", ["don't forget that ", "keep in mind that "])
def test_other_memory_phrases(client, phrase):
    response = client.post("/api/chat", json={"message": phrase + "milk is low"})
    assert response.get_json()["memory_saved"] is True
    memories = client.get("/api/memory").get_json()["memories"]
    assert memories[-1]["memory"] == "milk is low"


def test_empty_remember_payload_falls_through_to_llm(client, prototype):
    # "remember" with nothing after it does not match the "remember " prefix
    # (message is stripped), so it goes to the model.
    response = client.post("/api/chat", json={"message": "remember"})
    assert response.get_json() == {"response": "fake reply"}
    assert len(prototype.completions.calls) == 1


def test_memory_capped_at_100(prototype):
    for i in range(105):
        prototype.add_memory(f"item {i}")
    assert len(prototype.memory) == 100
    assert prototype.memory[0]["memory"] == "item 5"


def test_prompt_uses_only_last_20_memories(prototype):
    for i in range(25):
        prototype.add_memory(f"item {i}")
    text = prototype.memory_text().splitlines()
    assert len(text) == 20
    assert text[0] == "- item 5" and text[-1] == "- item 24"


def test_memory_endpoint_empty(client):
    assert client.get("/api/memory").get_json() == {"memories": []}


def test_corrupt_memory_file_loads_empty(prototype, tmp_path):
    (tmp_path / "data" / "kyvon_memory.json").write_text("{not json")
    assert prototype.load_memory() == []


def test_non_list_memory_file_loads_empty(prototype, tmp_path):
    (tmp_path / "data" / "kyvon_memory.json").write_text('{"a": 1}')
    assert prototype.load_memory() == []


# ---------------------------------------------------------------- web search


def test_web_prefix_uses_compound_model(client, prototype):
    response = client.post("/api/chat", json={"message": "web latest python release"})
    assert response.get_json() == {"response": "fake reply", "web": True}
    (call,) = prototype.completions.calls
    assert call["model"] == prototype.WEB_MODEL
    assert call["messages"][1]["content"] == "latest python release"


def test_web_without_query_falls_through_to_llm(client, prototype):
    # "web" alone (stripped) lacks the "web " prefix -> normal chat.
    response = client.post("/api/chat", json={"message": "web"})
    assert response.get_json() == {"response": "fake reply"}
    assert prototype.completions.calls[0]["model"] == prototype.MODEL


# ---------------------------------------------------------------- environment


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def fake_requests_get(url, **kwargs):
    if "nominatim" in url:
        return FakeResponse({"address": {"town": "Testville", "state": "TX", "country": "USA"}})
    return FakeResponse(
        {
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
    )


def test_environment_endpoint(client, prototype, monkeypatch):
    monkeypatch.setattr(prototype.requests, "get", fake_requests_get)
    response = client.post("/api/environment", json={"latitude": 1, "longitude": 2})
    assert response.status_code == 200
    body = response.get_json()
    assert body["location"] == {
        "city": "Testville",
        "state": "TX",
        "country": "USA",
        "display": "Testville, TX, USA",
    }
    assert body["weather"]["condition"] == "Partly cloudy"
    assert body["weather"]["temperature"] == 70.5
    assert body["weather"]["timezone"] == "America/Chicago"


def test_environment_bad_input_is_500(client):
    response = client.post("/api/environment", json={"latitude": "x"})
    assert response.status_code == 500
    assert "error" in response.get_json()


def test_location_failure_degrades_to_unknown(prototype, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(prototype.requests, "get", boom)
    assert prototype.get_location(1, 2)["display"] == "Unknown location"


def test_weather_failure_propagates(prototype, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(prototype.requests, "get", boom)
    with pytest.raises(RuntimeError):
        prototype.get_weather(1, 2)


def test_unknown_weather_code(prototype, monkeypatch):
    def get(url, **kwargs):
        return FakeResponse({"current": {"weather_code": 77}, "timezone": "UTC"})

    monkeypatch.setattr(prototype.requests, "get", get)
    assert prototype.get_weather(1, 2)["condition"] == "Unknown conditions"


# ---------------------------------------------------------------- status


def test_status_online(client, prototype):
    body = client.get("/api/status").get_json()
    assert body["online"] is True
    assert [d["name"] for d in body["diagnostics"]] == ["Python", "Memory", "Groq AI"]
    # Known quirk: status makes a live LLM call.
    assert len(prototype.completions.calls) == 1


def test_status_reports_llm_error(client, prototype):
    prototype.completions.error = RuntimeError("no groq")
    body = client.get("/api/status").get_json()
    assert body["online"] is False
    assert body["diagnostics"][-1] == {
        "name": "Groq AI",
        "status": "ERROR",
        "details": "no groq",
    }
