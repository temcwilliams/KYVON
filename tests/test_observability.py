"""Logging, request ids, error records, health and the owner's admin endpoints."""

import io
import json
import logging

import pytest
from sqlalchemy import select

from kyvon.llm.base import LLMResponse, ToolCall
from kyvon.logging_setup import JsonFormatter, TextFormatter, configure_logging
from kyvon.models import AgentRun, ErrorRecord, User
from kyvon.services import auth_service
from kyvon.services.observability import record_error, system_status, usage_summary
from tests.conftest import TEST_ENCRYPTION_KEY, TEST_PASSWORD


@pytest.fixture
def log_stream():
    """Capture KYVON's log output the way it would be written."""
    stream = io.StringIO()
    logger = logging.getLogger("kyvon")
    handler = logging.StreamHandler(stream)
    from kyvon.logging_setup import ContextFilter

    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield stream
    logger.removeHandler(handler)


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.fixture
def session(app):
    with app.extensions["kyvon"].session_factory() as s:
        yield s


# ------------------------------------------------------------ request ids


def test_every_response_has_a_request_id(anon_client):
    rid = anon_client.get("/api/v1/health").headers["X-Request-ID"]
    assert len(rid) == 16 and anon_client.get("/api/v1/health").headers["X-Request-ID"] != rid


def test_a_reasonable_incoming_id_is_kept(anon_client):
    response = anon_client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc.123_XYZ"})
    assert response.headers["X-Request-ID"] == "trace-abc.123_XYZ"


@pytest.mark.parametrize(
    "bad",
    ["short", "has space in it", "x" * 65, "<script>alert(1)</script>"],
)
def test_hostile_ids_are_replaced(anon_client, bad):
    got = anon_client.get("/api/v1/health", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
    assert got != bad and len(got) == 16


def test_error_responses_carry_the_id_too(anon_client):
    response = anon_client.get("/api/v1/nope")
    assert response.status_code == 404 and response.headers["X-Request-ID"]


# ------------------------------------------------------------ structured logs


def test_access_log_has_request_id_user_and_timing_but_no_secrets(client, log_stream):
    client.post(
        "/api/v1/chat",
        json={"message": "my secret is gsk_" + "a" * 30},
        headers={"X-Request-ID": "req-12345678"},
    )
    entries = [e for e in lines(log_stream) if e["logger"] == "kyvon.access"]
    entry = next(e for e in entries if "chat" in e["message"])
    assert (
        entry["request_id"] == "req-12345678"
        and entry["status"] == 200
        and entry["duration_ms"] >= 0
    )
    assert entry["user_id"] and entry["message"] == "POST /api/v1/chat -> 200"
    text = log_stream.getvalue()
    assert "gsk_" not in text and "my secret" not in text  # bodies are never logged


def test_query_strings_are_not_logged(client, log_stream):
    client.get("/api/v1/memories?q=very-private-search-term")
    assert "very-private-search-term" not in log_stream.getvalue()


def test_health_checks_do_not_spam_the_log(anon_client, log_stream):
    anon_client.get("/api/v1/health")
    assert log_stream.getvalue() == ""


def test_the_logger_redacts_secrets_in_messages(log_stream):
    logging.getLogger("kyvon.test").info("token=%s Bearer abcdefghijklmnop1234", "kyv_" + "x" * 30)
    text = log_stream.getvalue()
    assert "kyv_xxxx" not in text and "abcdefghijklmnop1234" not in text


def test_json_and_text_formats():
    record = logging.LogRecord("kyvon.x", logging.WARNING, "f", 1, "hello %s", ("world",), None)
    record.request_id = "rid-1"
    record.extra_field = 5
    entry = json.loads(JsonFormatter().format(record))
    assert (
        entry["message"] == "hello world"
        and entry["level"] == "WARNING"
        and entry["request_id"] == "rid-1"
    )
    assert entry["extra_field"] == 5 and entry["ts"].endswith("+00:00")
    assert "hello world" in TextFormatter().format(record) and "[rid-1]" in TextFormatter().format(
        record
    )


def test_exceptions_are_logged_redacted():
    try:
        raise RuntimeError("failed with password=hunter2 and gsk_" + "b" * 30)
    except RuntimeError:
        import sys

        record = logging.LogRecord("kyvon.x", logging.ERROR, "f", 1, "boom", (), sys.exc_info())
    text = JsonFormatter().format(record)
    assert "hunter2" not in text and "gsk_bbbb" not in text


def test_configure_logging_is_idempotent():
    configure_logging("INFO")
    configure_logging("DEBUG", json_format=True)
    marked = [h for h in logging.getLogger("kyvon").handlers if getattr(h, "_kyvon_handler", False)]
    assert len(marked) == 1 and isinstance(marked[0].formatter, JsonFormatter)


def test_production_defaults_to_json_logs():
    from kyvon.config import Settings

    assert Settings.from_env({"GROQ_API_KEY": "k", "KYVON_ENV": "production"}).log_json is True
    assert Settings.from_env({"GROQ_API_KEY": "k"}).log_json is False
    assert (
        Settings.from_env(
            {"GROQ_API_KEY": "k", "KYVON_ENV": "production", "KYVON_LOG_JSON": "false"}
        ).log_json
        is False
    )


# ------------------------------------------------------------ error records


def test_error_log_also_writes_a_redacted_database_record(app, client, session, settings):
    svc = app.extensions["kyvon"]
    client.get("/api/v1/memories", headers={"X-Request-ID": "req-abcdef12"})
    svc.error_log.log(
        "Test Error", "failed for key gsk_" + "c" * 30, "Traceback... password=hunter2"
    )
    row = session.scalar(select(ErrorRecord))
    assert (
        row.kind == "Test Error" and "gsk_cccc" not in row.message and "hunter2" not in row.details
    )
    assert "TYPE: Test Error" in settings.error_log.read_text()  # the file log still works


def test_errors_get_the_request_id_and_user(client, app, session, fake_llm):
    fake_llm.error = RuntimeError("model down")
    client.post("/api/v1/chat", json={"message": "hi"}, headers={"X-Request-ID": "trace-99999999"})
    row = session.scalar(select(ErrorRecord).where(ErrorRecord.kind == "Chat Error"))
    assert row.request_id == "trace-99999999" and row.user_id is not None


def test_a_broken_sink_never_breaks_the_caller(app, tmp_path):
    from kyvon.utils.error_log import ErrorLog

    def boom(*a):
        raise RuntimeError("db down")

    log = ErrorLog(tmp_path / "e.log", sink=boom)
    log.log("X", "still written", "")
    assert "still written" in (tmp_path / "e.log").read_text()


def test_unhandled_errors_are_recorded(client, session, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("kyvon.services.memory_service.MemoryService.list", explode)
    assert client.get("/api/v1/memories").status_code == 500
    assert session.scalar(select(ErrorRecord.kind)) == "Unhandled Error"


# ------------------------------------------------------------ health


def test_liveness_and_readiness(anon_client):
    assert anon_client.get("/api/v1/health").get_json() == {"status": "ok"}
    assert anon_client.get("/api/v1/health/ready").get_json() == {"status": "ready"}


def test_readiness_reports_a_broken_database_without_details(app, anon_client, monkeypatch):
    def broken():
        raise RuntimeError("no database at /secret/path")

    monkeypatch.setattr(app.extensions["kyvon"], "session_factory", broken)
    response = anon_client.get("/api/v1/health/ready")
    assert response.status_code == 503 and response.get_json() == {"status": "unavailable"}
    assert "secret" not in response.get_data(as_text=True)


# ------------------------------------------------------------ admin API


def test_status_shape_and_no_secrets(client, settings):
    status = client.get("/api/v1/admin/status").get_json()
    assert status["healthy"] is True and status["database"]["ok"] is True
    assert status["database"]["counts"]["users"] == 1 and status["database"]["size_bytes"] > 0
    assert status["llm"] == {"provider": "groq", "model": settings.model, "configured": True}
    assert status["integrations"]["calendar"] == {"configured": True, "connected_accounts": 0}
    assert status["integrations"]["logseq"] == {"configured": False}
    assert status["scheduler"]["enabled"] is False and status["tools"]["registered"] > 20
    assert status["disk"]["free_bytes"] > 0
    text = json.dumps(status)
    for secret in ("test-key", TEST_ENCRYPTION_KEY, "test-client-secret", TEST_PASSWORD):
        assert secret not in text


def test_migration_state_is_reported(client):
    db = client.get("/api/v1/admin/status").get_json()["database"]
    assert (
        "migration" in db and "up_to_date" in db
    )  # the test schema is created directly, not migrated


def test_deep_status_calls_the_model_once(client, fake_llm):
    fake_llm.reply = "ONLINE"
    assert client.get("/api/v1/admin/status").get_json()["llm"].get("reachable") is None
    assert fake_llm.calls == []
    deep = client.get("/api/v1/admin/status?deep=1").get_json()
    assert deep["llm"]["reachable"] is True and len(fake_llm.calls) == 1


def test_deep_status_reports_llm_failure_without_details(client, fake_llm):
    fake_llm.error = RuntimeError("bad key gsk_" + "d" * 30)
    deep = client.get("/api/v1/admin/status?deep=1").get_json()
    assert deep["llm"] == {
        "provider": "groq",
        "model": deep["llm"]["model"],
        "configured": True,
        "reachable": False,
        "error": "RuntimeError",
    }
    assert deep["healthy"] is False and "gsk_" not in json.dumps(deep)


def test_status_counts_reflect_activity(client, app, session):
    client.post("/api/v1/chat", json={"message": "hello"})
    record_error(session, "Boom", "x", "")
    status = client.get("/api/v1/admin/status").get_json()
    assert status["errors"] == {"unresolved": 1, "last_24h": 1}
    assert status["database"]["counts"]["messages"] == 2


def test_errors_endpoint_and_resolution(client, session):
    first = record_error(session, "A", "first problem gsk_" + "e" * 30, "trace")
    record_error(session, "B", "second problem", "")
    listed = client.get("/api/v1/admin/errors").get_json()["errors"]
    assert [e["kind"] for e in listed] == ["B", "A"] and "gsk_eeee" not in json.dumps(listed)
    resolved = client.post(
        f"/api/v1/admin/errors/{first.id}/resolve", json={"note": "rotated the key"}
    ).get_json()["error"]
    assert resolved["resolved"] is True and resolved["resolution"] == "rotated the key"
    assert [
        e["kind"] for e in client.get("/api/v1/admin/errors?resolved=false").get_json()["errors"]
    ] == ["B"]
    assert [
        e["kind"] for e in client.get("/api/v1/admin/errors?resolved=true").get_json()["errors"]
    ] == ["A"]
    assert client.post("/api/v1/admin/errors/999/resolve", json={}).status_code == 404
    assert client.get("/api/v1/admin/errors?limit=x").status_code == 400


def test_usage_summary(client, fake_llm, session):
    client.post("/api/v1/chat", json={"message": "one"})
    client.post("/api/v1/chat", json={"message": "two"})
    fake_llm.script = [LLMResponse(tool_calls=[ToolCall("c", "get_current_time", "{}")]), "done"]
    client.post("/api/v1/chat", json={"message": "three"})
    usage = client.get("/api/v1/admin/usage").get_json()
    assert usage["assistant_replies"] == 3 and usage["chat_tokens"] == {"in": 40, "out": 20}
    assert usage["tool_calls_by_tool"] == {"get_current_time": 1} and usage[
        "tool_calls_by_status"
    ] == {"succeeded": 1}
    assert usage_summary(session, days=1)["assistant_replies"] == 3


def test_automation_runs_listing_is_scoped(app, client, anon_client, owner):
    from kyvon.automation.runner import AutomationRunner
    from kyvon.services.automation_service import AutomationService

    svc = app.extensions["kyvon"]
    with svc.session_factory() as s:
        a = AutomationService(s, owner.id, timezone="UTC").create(
            "Mine", "reminder", {"type": "daily", "time": "08:00"}, text="hi"
        )
        AutomationRunner(svc).execute(s, a.id, triggered_by="manual")
        other = User(username="stranger", password_hash="x")
        s.add(other)
        s.commit()
        raw, _ = auth_service.issue_token(s, other, name="t", ttl_days=1)
    assert len(client.get("/api/v1/admin/automation-runs").get_json()["runs"]) == 1
    assert (
        anon_client.get(
            "/api/v1/admin/automation-runs", headers={"Authorization": f"Bearer {raw}"}
        ).get_json()["runs"]
        == []
    )


def test_admin_requires_auth(anon_client, owner):
    for path in (
        "/api/v1/admin/status",
        "/api/v1/admin/errors",
        "/api/v1/admin/usage",
        "/api/v1/admin/automation-runs",
    ):
        assert anon_client.get(path).status_code == 401
    assert anon_client.post("/api/v1/admin/errors/1/resolve", json={}).status_code == 401


# ------------------------------------------------------------ diagnostics tools and agent


def call(call_id, tool, /, **arguments):
    return ToolCall(call_id, tool, json.dumps(arguments))


def test_diagnostics_tools_via_chat(client, session, fake_llm):
    record_error(session, "Weather Error", "open-meteo timed out", "")
    fake_llm.script = [
        LLMResponse(tool_calls=[call("c1", "system_status"), call("c2", "recent_errors")]),
        "Weather lookups are timing out.",
    ]
    client.post("/api/v1/chat", json={"message": "is everything ok?"})
    results = [
        json.loads(m["content"]) for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"
    ]
    assert results[0]["data"]["healthy"] is True and "counts" not in results[0]["data"]["database"]
    assert results[1]["data"][0]["kind"] == "Weather Error" and results[1]["untrusted"] is True


def test_diagnostics_agent(app, owner, session, fake_llm):
    svc = app.extensions["kyvon"]
    record_error(session, "Calendar OAuth Error", "state expired", "")
    fake_llm.script = [
        LLMResponse(tool_calls=[call("c1", "recent_errors")]),
        "Your calendar sign-in link expired; connect again.",
    ]
    run = svc.agent_runner.create_run(
        session, owner.id, "diagnostics", "why did my calendar connection fail?"
    )
    run = svc.agent_runner.run(session, run.id)
    assert run.status == "succeeded" and "expired" in run.result
    assert session.scalar(select(AgentRun.agent)) == "diagnostics"


def test_system_status_function_directly(app, session):
    status = system_status(session, app.extensions["kyvon"])
    assert status["environment"] == "development" and status["version"]
