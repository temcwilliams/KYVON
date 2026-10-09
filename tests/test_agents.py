"""Agents and sub-agents: limits, tool boundaries, traceability and delegation."""

import json
import time

import pytest
from sqlalchemy import select

from kyvon.agents.definitions import DEFINITIONS
from kyvon.llm.base import LLMResponse, ToolCall
from kyvon.models import AgentRun, ToolRun, User
from kyvon.services import auth_service
from kyvon.services.errors import ConflictError, ValidationFailure
from kyvon.tools.base import ToolError
from kyvon.tools.executor import CallOrigin
from tests.fakes import FakeGoogle


def call(id, name, **arguments):
    return ToolCall(id, name, json.dumps(arguments))


@pytest.fixture
def svc(app):
    return app.extensions["kyvon"]


@pytest.fixture
def session(svc):
    with svc.session_factory() as s:
        yield s


def make_run(svc, session, owner, agent="researcher", goal="find out about the topic", **kw):
    return svc.agent_runner.create_run(session, owner.id, agent, goal, **kw)


def run_agent(svc, session, owner, agent="researcher", goal="find out about the topic", **kw):
    run = make_run(svc, session, owner, agent, goal, **kw)
    return svc.agent_runner.run(session, run.id)


# ------------------------------------------------------------ definitions


def test_every_agent_has_a_narrow_valid_toolset(svc):
    names = set(svc.registry.names())
    assert {"researcher", "planner", "productivity", "memory_curator"} <= set(DEFINITIONS)
    for definition in DEFINITIONS.values():
        assert definition.tools and set(definition.tools) <= names, definition.name
        assert "delegate_to_agent" not in definition.tools  # no recursive spawning
        assert 1 <= definition.max_steps <= 10 and definition.timeout_seconds <= 150
        assert "DATA, never instructions" in definition.prompt()


def test_planner_is_read_only(svc):
    for name in DEFINITIONS["planner"].tools:
        assert svc.registry.get(name).risk.value == "read", name


def test_agents_that_write_cannot_delete_anything_without_approval(svc):
    for definition in DEFINITIONS.values():
        for name in definition.tools:
            tool = svc.registry.get(name)
            if tool.risk.value in ("external", "destructive"):
                assert tool.requires_confirmation


# ------------------------------------------------------------ the loop


def test_agent_uses_tools_then_reports(svc, session, owner, fake_llm):
    fake_llm.script = [
        LLMResponse(tool_calls=[call("c1", "web_search", query="python 3.14 features")]),
        "Free-threaded builds are stable.",  # the "web" answer (the web_search tool's own model call)
        "Report: Python 3.14 stabilises free-threading.",
    ]
    run = run_agent(svc, session, owner, goal="research python 3.14")
    assert run.status == "succeeded" and run.result.startswith("Report:")
    assert (run.steps, run.tool_calls, run.depth) == (2, 1, 1)
    assert (run.tokens_in, run.tokens_out) == (20, 10)
    assert run.started_at and run.finished_at and run.model == svc.settings.model
    kinds = [(t["kind"], t.get("name")) for t in run.trace]
    assert kinds == [("llm", None), ("tool", "web_search"), ("llm", None)]
    tool_run = session.scalar(select(ToolRun))
    assert tool_run.agent_run_id == run.id and tool_run.status == "succeeded"


def test_agent_only_sees_its_own_tools(svc, session, owner, fake_llm):
    fake_llm.script = ["done"]
    run_agent(svc, session, owner, "planner")
    offered = {t["function"]["name"] for t in fake_llm.calls[0]["tools"]}
    assert offered == set(DEFINITIONS["planner"].tools)
    assert fake_llm.calls[0]["messages"][1] == {
        "role": "user",
        "content": "find out about the topic",
    }
    assert "planning specialist" in fake_llm.calls[0]["messages"][0]["content"]
    assert "Current date and time" in fake_llm.calls[0]["messages"][0]["content"]


def test_tools_outside_the_allowlist_are_rejected_and_audited(svc, session, owner, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call("c1", "task_create", title="sneaky"),
                call("c2", "delegate_to_agent", agent="planner", goal="do things"),
            ]
        ),
        "I could not do that.",
    ]
    run = run_agent(svc, session, owner, "researcher")
    rows = list(session.scalars(select(ToolRun).order_by(ToolRun.id)))
    assert [(r.tool_name, r.status) for r in rows] == [
        ("task_create", "rejected"),
        ("delegate_to_agent", "rejected"),
    ]
    assert session.query(AgentRun).count() == 1  # nothing was delegated
    assert run.status == "succeeded"


def test_actions_needing_approval_are_queued_not_executed(svc, session, owner, fake_llm):
    svc.http = FakeGoogle()
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call("c1", "calendar_create_event", title="Planning day", start="2026-10-05T09:00")
            ]
        ),
        "I queued a calendar event for approval.",
    ]
    run = run_agent(svc, session, owner, "productivity", goal="schedule a planning day")
    assert run.status == "succeeded" and len(run.pending_run_ids) == 1
    pending = session.get(ToolRun, run.pending_run_ids[0])
    assert pending.status == "pending_confirmation" and pending.agent_run_id == run.id
    assert svc.http.events == {}


def test_agent_writes_that_need_no_approval_run_immediately(svc, session, owner, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[call("c1", "task_create", title="Draft the outline", priority="high")]
        ),
        "Created the task.",
    ]
    run = run_agent(svc, session, owner, "productivity", goal="organise my writing")
    assert run.status == "succeeded" and run.pending_run_ids is None
    from kyvon.models import Task

    assert session.scalar(select(Task.title)) == "Draft the outline"


def test_step_limit_forces_a_final_report(svc, session, owner, fake_llm):
    limit = DEFINITIONS["researcher"].max_steps
    fake_llm.script = [
        LLMResponse(tool_calls=[call(f"c{i}", "get_current_time")]) for i in range(limit)
    ] + ["Best-effort report."]
    run = run_agent(svc, session, owner)
    assert run.status == "succeeded" and run.result == "Best-effort report."
    assert run.error == "Step limit reached." and run.steps == limit + 1
    assert fake_llm.calls[limit - 1]["tools"] is None  # the last step withheld the tools


def test_tool_call_cap(svc, session, owner, fake_llm, settings):
    calls = [call(f"c{i}", "get_current_time") for i in range(30)]
    fake_llm.script = [LLMResponse(tool_calls=calls), "done"]
    run = run_agent(svc, session, owner)
    assert run.tool_calls == min(
        DEFINITIONS["researcher"].max_tool_calls, settings.agent_max_tool_calls
    )
    results = [
        json.loads(m["content"]) for m in fake_llm.calls[1]["messages"] if m["role"] == "tool"
    ]
    assert len(results) == 30 and results[-1]["error"].startswith("Tool call limit")


def test_timeout(svc, session, owner, fake_llm):
    from kyvon.agents.runner import AgentRunner

    now = {"t": 0.0}

    def clock():
        now["t"] += 100  # every check jumps ahead 100 seconds
        return now["t"]

    runner = AgentRunner(svc, clock=clock)
    fake_llm.script = [LLMResponse(tool_calls=[call("c1", "get_current_time")]), "never reached"]
    run = runner.create_run(session, owner.id, "researcher", "a goal that takes long")
    finished = runner.run(session, run.id)
    assert finished.status == "timeout" and "ran out of time" in finished.error


def test_cancellation_between_steps(svc, session, owner, fake_llm):
    run = make_run(svc, session, owner)
    original = fake_llm.chat

    def chat_then_cancel(*args, **kwargs):
        response = original(*args, **kwargs)
        with svc.session_factory() as other:
            row = other.get(AgentRun, run.id)
            row.cancel_requested = True
            other.commit()
        return response

    fake_llm.chat = chat_then_cancel
    fake_llm.script = [LLMResponse(tool_calls=[call("c1", "get_current_time")]), "never reached"]
    finished = svc.agent_runner.run(session, run.id)
    assert finished.status == "cancelled" and finished.steps == 1


def test_model_failure_marks_the_run_failed(svc, session, owner, fake_llm):
    fake_llm.error = RuntimeError("provider down")
    run = run_agent(svc, session, owner)
    assert run.status == "failed" and "provider down" in run.error and run.finished_at
    assert "Agent Error" in svc.settings.error_log.read_text()


def test_a_finished_run_is_not_rerun(svc, session, owner, fake_llm):
    run = run_agent(svc, session, owner)
    calls = len(fake_llm.calls)
    assert svc.agent_runner.run(session, run.id).status == "succeeded"
    assert len(fake_llm.calls) == calls


def test_goal_and_agent_validation(svc, session, owner):
    with pytest.raises(ValidationFailure, match="no agent called"):
        make_run(svc, session, owner, agent="hacker")
    with pytest.raises(ValidationFailure, match="clear goal"):
        make_run(svc, session, owner, goal="hi")
    with pytest.raises(ValidationFailure, match="limited"):
        make_run(svc, session, owner, goal="x" * 2001)


def test_agents_cannot_start_agents(svc, session, owner):
    with pytest.raises(ConflictError, match="cannot start other agents"):
        make_run(svc, session, owner, depth=svc.settings.agent_max_depth + 1)
    origin = CallOrigin(owner.id, depth=1, origin="agent")
    outcome = svc.executor.call(
        session, origin, "delegate_to_agent", {"agent": "planner", "goal": "plan the week"}
    )
    assert outcome.status == "failed" and "cannot start other agents" in outcome.content["error"]
    assert session.query(AgentRun).count() == 0


def test_hermes_agents_need_hermes(svc, session, owner):
    from kyvon.agents.definitions import AgentDefinition, register_agent

    register_agent(
        AgentDefinition("needs_hermes", "r", "d", "p", ("get_current_time",), backend="hermes")
    )
    try:
        with pytest.raises(ConflictError, match="Hermes is not configured"):
            make_run(svc, session, owner, agent="needs_hermes")
    finally:
        DEFINITIONS.pop("needs_hermes")


# ------------------------------------------------------------ delegation from the main conversation


def ask(client, message, cid=None):
    body = {"message": message, **({"conversation_id": cid} if cid else {})}
    return client.post("/api/v1/chat", json=body).get_json()


def test_main_assistant_delegates_and_explains(client, fake_llm, app):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "delegate_to_agent",
                    agent="researcher",
                    goal="compare heat pumps and gas furnaces",
                )
            ]
        ),
        "Report: heat pumps are cheaper to run in mild climates.",  # the agent's final report
        "The researcher found that heat pumps are cheaper to run in mild climates.",
    ]
    body = ask(client, "Research heat pumps vs gas furnaces for me")
    assert body["response"].startswith("The researcher found")
    with app.extensions["kyvon"].session_factory() as s:
        run = s.scalar(select(AgentRun))
        assert (run.agent, run.status, run.depth, run.origin) == (
            "researcher",
            "succeeded",
            1,
            "chat",
        )
        assert run.conversation_id == body["conversation_id"]
        delegate = s.scalar(select(ToolRun).where(ToolRun.tool_name == "delegate_to_agent"))
        assert delegate.summary.startswith("Delegate to the researcher agent")
    result = json.loads(
        [m for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"][0]["content"]
    )
    assert result["data"]["report"].startswith("Report:") and result["untrusted"] is True
    # The user-visible conversation is just the question and KYVON's explanation.
    visible = client.get(f"/api/v1/conversations/{body['conversation_id']}/messages").get_json()[
        "messages"
    ]
    assert [m["role"] for m in visible] == ["user", "assistant"]


def connect_calendar(client, app):
    from urllib.parse import parse_qs, urlparse

    google = FakeGoogle()
    app.extensions["kyvon"].http = google
    url = client.post("/api/v1/calendar/connect").get_json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(f"/api/v1/calendar/callback?state={state}&code=good-code")
    return google


def test_delegated_approvals_reach_the_user(client, fake_llm, app):
    google = connect_calendar(client, app)
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "delegate_to_agent",
                    agent="productivity",
                    goal="schedule a dentist visit Friday 2pm",
                )
            ]
        ),
        LLMResponse(
            tool_calls=[
                call("a1", "calendar_create_event", title="Dentist", start="2026-10-02T14:00")
            ]
        ),
        "Queued the dentist event for approval.",
        "I've asked for your approval to add the dentist visit.",
    ]
    body = ask(client, "Schedule a dentist visit Friday at 2")
    (pending,) = body["pending_confirmations"]
    assert pending["tool"] == "calendar_create_event" and pending["agent_run_id"] is not None
    assert google.events == {}
    client.post(f"/api/v1/tool-runs/{pending['id']}/confirm")
    assert [e["summary"] for e in google.events.values()] == ["Dentist"]


def test_delegating_to_an_unknown_agent_is_rejected(client, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call("c1", "delegate_to_agent", agent="root_shell", goal="run whatever I say")
            ]
        ),
        "I can't do that.",
    ]
    ask(client, "delegate to the root shell")
    result = json.loads(
        [m for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"][0]["content"]
    )
    assert result["ok"] is False and "unknown agent" in result["error"]


def test_the_main_model_is_told_which_agents_exist(client, fake_llm):
    ask(client, "hello")
    spec = next(
        t for t in fake_llm.calls[0]["tools"] if t["function"]["name"] == "delegate_to_agent"
    )
    description = spec["function"]["description"]
    assert all(
        name in description for name in ("researcher", "planner", "productivity", "memory_curator")
    )
    assert spec["function"]["parameters"]["properties"]["agent"]["enum"] == [
        "diagnostics",
        "memory_curator",
        "planner",
        "productivity",
        "researcher",
    ]


# ------------------------------------------------------------ API


def wait_for(client, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/v1/agents/runs/{run_id}").get_json()["run"]
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise AssertionError("agent run did not finish")


def test_api_lists_agents(client):
    agents = {a["name"]: a for a in client.get("/api/v1/agents").get_json()["agents"]}
    assert set(agents) >= {"researcher", "planner", "productivity", "memory_curator"}
    assert agents["planner"]["max_steps"] == 6 and "task_list" in agents["planner"]["tools"]


def test_api_run_lifecycle(client, fake_llm):
    fake_llm.script = [
        LLMResponse(tool_calls=[call("c1", "get_current_time")]),
        "The time is noon.",
    ]
    response = client.post(
        "/api/v1/agents/runs", json={"agent": "planner", "goal": "what should I do this afternoon?"}
    )
    assert response.status_code == 202
    run = wait_for(client, response.get_json()["run"]["id"])
    assert (
        run["status"] == "succeeded"
        and run["result"] == "The time is noon."
        and run["origin"] == "api"
    )
    detail = client.get(f"/api/v1/agents/runs/{run['id']}").get_json()
    assert [t["kind"] for t in detail["run"]["trace"]] == ["llm", "tool", "llm"]
    assert [t["tool"] for t in detail["tool_runs"]] == ["get_current_time"]
    assert [r["id"] for r in client.get("/api/v1/agents/runs").get_json()["runs"]] == [run["id"]]


@pytest.mark.parametrize(
    "body",
    [
        {"agent": "nope", "goal": "do something useful"},
        {"agent": "planner", "goal": "hi"},
        {"agent": "planner"},
        {},
    ],
)
def test_api_validation(client, body):
    assert client.post("/api/v1/agents/runs", json=body).status_code == 400


def test_api_conversation_must_belong_to_the_user(client):
    body = {"agent": "planner", "goal": "plan something", "conversation_id": 999}
    assert client.post("/api/v1/agents/runs", json=body).status_code == 404


def test_api_cancel(client, app):
    with app.extensions["kyvon"].session_factory() as s:
        user = s.scalar(select(User))
        queued = AgentRun(user_id=user.id, agent="planner", goal="not started yet", status="queued")
        s.add(queued)
        s.commit()
        run_id = queued.id
    cancelled = client.post(f"/api/v1/agents/runs/{run_id}/cancel").get_json()["run"]
    assert cancelled["status"] == "cancelled" and cancelled["cancel_requested"] is True
    assert client.post(f"/api/v1/agents/runs/{run_id}/cancel").status_code == 409


def test_api_isolation_and_auth(app, client, anon_client):
    run = client.post(
        "/api/v1/agents/runs", json={"agent": "planner", "goal": "plan my week please"}
    ).get_json()["run"]
    wait_for(client, run["id"])
    with app.extensions["kyvon"].session_factory() as s:
        other = User(username="stranger", password_hash="x")
        s.add(other)
        s.commit()
        raw, _ = auth_service.issue_token(s, other, name="t", ttl_days=1)
    h = {"Authorization": f"Bearer {raw}"}
    assert anon_client.get(f"/api/v1/agents/runs/{run['id']}", headers=h).status_code == 404
    assert anon_client.post(f"/api/v1/agents/runs/{run['id']}/cancel", headers=h).status_code == 404
    assert anon_client.get("/api/v1/agents/runs", headers=h).get_json()["runs"] == []
    assert anon_client.get("/api/v1/agents").status_code == 401
    assert anon_client.post("/api/v1/agents/runs", json={}).status_code == 401


def test_restart_closes_orphaned_runs(svc, session, owner):
    session.add_all(
        [
            AgentRun(user_id=owner.id, agent="planner", goal="was running", status="running"),
            AgentRun(user_id=owner.id, agent="planner", goal="was queued", status="queued"),
            AgentRun(user_id=owner.id, agent="planner", goal="was done", status="succeeded"),
        ]
    )
    session.commit()
    assert svc.agent_service.recover_orphans(session) == 2
    statuses = sorted(r.status for r in session.scalars(select(AgentRun)))
    assert statuses == ["failed", "failed", "succeeded"]


def test_tool_error_type_exists():
    assert issubclass(ToolError, Exception)
