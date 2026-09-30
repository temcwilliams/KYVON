"""Tasks: service rules, recurrence, time zones, tools and API."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kyvon.db import Base, make_engine, make_session_factory
from kyvon.llm.base import LLMResponse, ToolCall
from kyvon.models import Task, User
from kyvon.services.errors import NotFoundError, ValidationFailure
from kyvon.services.task_service import TaskService
from kyvon.services.tasks_time import next_occurrence, parse_due

CHI = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # 10:00 in Chicago (CDT)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def users(session):
    a, b = User(username="a", password_hash="x"), User(username="b", password_hash="x")
    session.add_all([a, b])
    session.commit()
    return a, b


@pytest.fixture
def tasks(session, users):
    return TaskService(session, users[0].id, timezone="America/Chicago", now=lambda: NOW)


# ------------------------------------------------------------ date parsing


def test_parse_due_formats():
    assert parse_due("2026-10-03", CHI) == (datetime(2026, 10, 3, 5, 0, tzinfo=UTC), False)
    assert parse_due("2026-10-03T14:00", CHI) == (datetime(2026, 10, 3, 19, 0, tzinfo=UTC), True)
    assert parse_due("2026-10-03T14:00-05:00", CHI)[0] == datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
    assert parse_due("2026-10-03T19:00:00Z", CHI)[0] == datetime(2026, 10, 3, 19, 0, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["tomorrow", "10/03/2026", "2026-13-01", "", "next friday"])
def test_parse_due_rejects_non_iso(bad):
    with pytest.raises(ValidationFailure, match="ISO"):
        parse_due(bad, CHI)


def test_recurrence_keeps_wall_clock_across_dst():
    # 9 AM Chicago on Sat Nov 1 2026 (CDT); the clocks fall back on Sun Nov 1... check a week over it.
    start = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)  # 9:00 CDT
    nxt = next_occurrence(start, "weekly", 1, CHI)
    assert nxt.astimezone(CHI).hour == 9 and nxt.astimezone(CHI).date().isoformat() == "2026-11-07"
    assert nxt == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)  # 9:00 CST is 15:00 UTC


def test_monthly_recurrence_clamps_short_months():
    jan31 = datetime(2026, 1, 31, 18, 0, tzinfo=UTC)
    assert (
        next_occurrence(jan31, "monthly", 1, CHI).astimezone(CHI).date().isoformat() == "2026-02-28"
    )
    assert (
        next_occurrence(jan31, "yearly", 1, CHI).astimezone(CHI).date().isoformat() == "2027-01-31"
    )


# ------------------------------------------------------------ service


def test_create_and_serialize(tasks):
    task = tasks.create(
        "Call the dentist", due="2026-10-03T14:00", priority="high", notes="  ask about x "
    )
    data = tasks.serialize(task)
    assert data["title"] == "Call the dentist" and data["notes"] == "ask about x"
    assert data["priority"] == 3 and data["priority_name"] == "high"
    assert data["due"] == "2026-10-03T14:00:00-05:00" and data["due_has_time"] is True
    assert data["status"] == "open" and data["overdue"] is False and data["source"] == "user"


def test_date_only_due_is_reported_as_a_date(tasks):
    assert tasks.serialize(tasks.create("Pay rent", due="2026-10-05"))["due"] == "2026-10-05"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": "  "},
        {"title": "x" * 201},
        {"title": "ok", "priority": 9},
        {"title": "ok", "priority": "critical"},
        {"title": "ok", "due": "someday"},
        {"title": "ok", "recurrence": "hourly", "due": "2026-10-05"},
        {"title": "ok", "recurrence": "daily"},  # repeat needs a due date
        {"title": "ok", "recurrence": "daily", "due": "2026-10-05", "recurrence_interval": 0},
        {"title": "ok", "notes": "n" * 2001},
    ],
)
def test_create_validation(tasks, kwargs):
    with pytest.raises(ValidationFailure):
        tasks.create(**kwargs)


def test_overdue_rules(tasks):
    past_time = tasks.create("late timed", due="2026-10-01T09:00")  # 09:00 CDT < 10:00 now
    later_today = tasks.create("later today", due="2026-10-01T18:00")
    today_date = tasks.create("today date", due="2026-10-01")
    yesterday = tasks.create("yesterday", due="2026-09-30")
    flags = {
        t.title: tasks.serialize(t)["overdue"]
        for t in (past_time, later_today, today_date, yesterday)
    }
    assert flags == {
        "late timed": True,
        "later today": False,
        "today date": False,
        "yesterday": True,
    }


def test_list_ordering_filters_and_search(tasks):
    a = tasks.create("undated low", priority=1)
    b = tasks.create("soon", due="2026-10-02T09:00")
    c = tasks.create("sooner urgent", due="2026-10-02T08:00", priority=4)
    d = tasks.create("Buy MILK 100%", notes="from the store")
    assert [t.title for t in tasks.list()] == [
        "sooner urgent",
        "soon",
        "Buy MILK 100%",
        "undated low",
    ]
    assert [t.id for t in tasks.list(priority="urgent")] == [c.id]
    assert [t.id for t in tasks.list(query="milk")] == [d.id]
    assert [t.id for t in tasks.list(query="100%")] == [d.id] and tasks.list(query="%") == [d]
    assert [t.id for t in tasks.list(due_before="2026-10-02T08:30")] == [c.id]
    assert {t.id for t in tasks.list(due_after="2026-10-02T08:30")} == {b.id}
    assert a.id in {t.id for t in tasks.list(status="all")}
    with pytest.raises(ValidationFailure):
        tasks.list(status="weird")


def test_list_overdue_filter(tasks):
    tasks.create("late", due="2026-09-01")
    tasks.create("fine", due="2026-12-01")
    assert [t.title for t in tasks.list(overdue=True)] == ["late"]
    assert [t.title for t in tasks.list(overdue=False)] == ["fine"]


def test_update_semantics(tasks):
    task = tasks.create("draft", due="2026-10-05", recurrence="weekly", priority=1)
    tasks.update(task.id, title="final", priority="urgent")
    assert (task.title, task.priority) == ("final", 4) and task.recurrence == "weekly"
    tasks.update(task.id, due=None)  # None clears; UNSET leaves alone
    assert task.due_at is None
    tasks.update(task.id, recurrence=None)
    assert task.recurrence is None
    with pytest.raises(ValidationFailure):
        tasks.update(task.id, recurrence="daily")  # a repeat needs a due date


def test_complete_reopen_delete(tasks):
    task = tasks.create("one-off")
    done, follow = tasks.complete(task.id)
    assert done.status == "done" and done.completed_at == NOW and follow is None
    assert tasks.complete(task.id) == (done, None)  # idempotent
    assert tasks.list() == [] and [t.id for t in tasks.list(status="done")] == [task.id]
    assert tasks.reopen(task.id).status == "open" and task.completed_at is None
    tasks.delete(task.id)
    with pytest.raises(NotFoundError):
        tasks.get(task.id)


def test_completing_a_recurring_task_creates_the_next_one(tasks):
    task = tasks.create("Water plants", due="2026-10-01T18:00", recurrence="daily")
    done, follow = tasks.complete(task.id)
    assert done.status == "done"
    assert follow.status == "open" and follow.title == "Water plants"
    assert tasks.serialize(follow)["due"] == "2026-10-02T18:00:00-05:00"
    assert follow.recurrence == "daily" and follow.id != task.id


def test_recurring_task_completed_late_skips_missed_occurrences(tasks):
    task = tasks.create("Weekly review", due="2026-09-01T09:00", recurrence="weekly")
    _, follow = tasks.complete(task.id)
    assert follow.due_at > NOW
    assert (follow.due_at - NOW) <= timedelta(days=7)


def test_isolation_between_users(session, users):
    a = TaskService(session, users[0].id, timezone="UTC", now=lambda: NOW)
    b = TaskService(session, users[1].id, timezone="UTC", now=lambda: NOW)
    mine = a.create("private task")
    assert b.list(status="all") == [] and b.count_open() == 0
    for action in (b.get, b.reopen, b.delete, b.complete):
        with pytest.raises(NotFoundError):
            action(mine.id)
    with pytest.raises(NotFoundError):
        b.update(mine.id, title="hijack")
    assert session.get(Task, mine.id) is not None


# ------------------------------------------------------------ tools (natural language through the model)


def call(name, **args):
    return ToolCall("c1", name, json.dumps(args))


def chat(client, message, cid=None):
    body = {"message": message, **({"conversation_id": cid} if cid else {})}
    return client.post("/api/v1/chat", json=body).get_json()


def test_natural_language_task_creation_through_the_model(client, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "task_create", title="Call the dentist", due="2026-10-03T10:00", priority="high"
                )
            ]
        ),
        "Added: call the dentist on Friday at 10 AM.",
    ]
    body = chat(client, "Remind me to call the dentist Friday at 10")
    assert body["response"].startswith("Added")
    tasks = client.get("/api/v1/tasks").get_json()["tasks"]
    assert [(t["title"], t["priority_name"], t["source"]) for t in tasks] == [
        ("Call the dentist", "high", "assistant")
    ]
    system = fake_llm.calls[0]["messages"][0]["content"]
    assert "Current date and time" in system  # the model can resolve 'Friday' from this


def test_task_tools_reject_bad_input_without_side_effects(client, fake_llm):
    fake_llm.script = [
        LLMResponse(tool_calls=[call("task_create", title="x", due="whenever")]),
        LLMResponse(tool_calls=[call("task_create", title="x", secret_flag=True)]),
        "sorry",
    ]
    chat(client, "add a task")
    assert client.get("/api/v1/tasks").get_json()["tasks"] == []


def test_task_delete_needs_confirmation(client, fake_llm):
    task = client.post("/api/v1/tasks", json={"title": "keep me"}).get_json()["task"]
    fake_llm.script = [LLMResponse(tool_calls=[call("task_delete", task_id=task["id"])]), "waiting"]
    body = chat(client, "delete that task")
    (pending,) = body["pending_confirmations"]
    assert pending["summary"] == 'Delete the task "keep me"'
    assert len(client.get("/api/v1/tasks").get_json()["tasks"]) == 1
    client.post(f"/api/v1/tool-runs/{pending['id']}/confirm")
    assert client.get("/api/v1/tasks").get_json()["tasks"] == []


def test_complete_task_via_tool_and_recurring_follow_up(client, fake_llm):
    task = client.post(
        "/api/v1/tasks", json={"title": "Stretch", "due": "2026-12-01T08:00", "recurrence": "daily"}
    ).get_json()["task"]
    fake_llm.script = [LLMResponse(tool_calls=[call("task_complete", task_id=task["id"])]), "Done!"]
    chat(client, "I stretched")
    open_tasks = client.get("/api/v1/tasks").get_json()["tasks"]
    assert [t["due"][:10] for t in open_tasks] == ["2026-12-02"]


def test_task_tools_are_scoped_to_the_user(app, client, fake_llm):
    from kyvon.services.task_service import TaskService

    with app.extensions["kyvon"].session_factory() as s:
        other = User(username="stranger", password_hash="x")
        s.add(other)
        s.commit()
        theirs = TaskService(s, other.id, timezone="UTC").create("their task")
    fake_llm.script = [
        LLMResponse(
            tool_calls=[call("task_list", status="all"), call("task_complete", task_id=theirs.id)]
        ),
        "ok",
    ]
    chat(client, "list tasks")
    results = [
        json.loads(m["content"]) for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"
    ]
    assert results[0]["data"] == [] and results[1]["ok"] is False


# ------------------------------------------------------------ API


def test_api_crud_flow(client):
    created = client.post(
        "/api/v1/tasks",
        json={"title": "Write report", "due": "2026-12-01", "priority": "high", "notes": "n"},
    )
    assert created.status_code == 201
    task = created.get_json()["task"]
    url = f"/api/v1/tasks/{task['id']}"
    assert client.get(url).get_json()["task"]["priority_name"] == "high"

    patched = client.patch(url, json={"title": "Write final report", "due": None, "priority": 4})
    body = patched.get_json()["task"]
    assert body["title"] == "Write final report" and body["due"] is None and body["priority"] == 4

    done = client.post(url + "/complete").get_json()
    assert done["task"]["status"] == "done" and done["next_task"] is None
    assert client.get("/api/v1/tasks").get_json()["tasks"] == []
    assert len(client.get("/api/v1/tasks?status=done").get_json()["tasks"]) == 1
    assert client.post(url + "/reopen").get_json()["task"]["status"] == "open"
    assert client.delete(url).status_code == 200
    assert client.get(url).status_code == 404


def test_api_list_filters_and_open_count(client):
    for title, extra in [
        ("a", {"priority": 1}),
        ("b", {"due": "2020-01-01"}),
        ("c", {"due": "2099-01-01"}),
    ]:
        client.post("/api/v1/tasks", json={"title": title, **extra})
    listed = client.get("/api/v1/tasks?overdue=true").get_json()
    assert [t["title"] for t in listed["tasks"]] == ["b"] and listed["open_count"] == 3
    assert [t["title"] for t in client.get("/api/v1/tasks?priority=1").get_json()["tasks"]] == ["a"]
    assert [t["title"] for t in client.get("/api/v1/tasks?q=c").get_json()["tasks"]] == ["c"]
    assert client.get("/api/v1/tasks?limit=x").status_code == 400
    assert client.get("/api/v1/tasks?status=bogus").status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "x", "due": "tomorrow"},
        {"title": "x", "priority": "max"},
        {"title": "x", "recurrence": "daily"},
    ],
)
def test_api_validation(client, body):
    assert client.post("/api/v1/tasks", json=body).status_code == 400


def test_api_recurring_completion_returns_next_task(client):
    task = client.post(
        "/api/v1/tasks", json={"title": "Rent", "due": "2099-01-15", "recurrence": "monthly"}
    ).get_json()["task"]
    done = client.post(f"/api/v1/tasks/{task['id']}/complete").get_json()
    assert done["next_task"]["due"] == "2099-02-15"


def test_api_isolation_and_auth(app, client, anon_client):
    from kyvon.services import auth_service

    mine = client.post("/api/v1/tasks", json={"title": "private"}).get_json()["task"]
    with app.extensions["kyvon"].session_factory() as s:
        other = User(username="stranger", password_hash="x")
        s.add(other)
        s.commit()
        raw, _ = auth_service.issue_token(s, other, name="t", ttl_days=1)
    h = {"Authorization": f"Bearer {raw}"}
    url = f"/api/v1/tasks/{mine['id']}"
    assert anon_client.get(url, headers=h).status_code == 404
    assert anon_client.patch(url, json={"title": "x"}, headers=h).status_code == 404
    assert anon_client.post(url + "/complete", headers=h).status_code == 404
    assert anon_client.delete(url, headers=h).status_code == 404
    assert anon_client.get("/api/v1/tasks?status=all", headers=h).get_json()["tasks"] == []
    assert anon_client.get("/api/v1/tasks").status_code == 401


def test_task_times_follow_the_users_timezone_setting(app, client):
    with app.extensions["kyvon"].session_factory() as s:
        user = s.query(User).one()
        user.settings = {"timezone": "Asia/Tokyo"}
        s.commit()
    task = client.post("/api/v1/tasks", json={"title": "t", "due": "2026-10-03T09:00"}).get_json()[
        "task"
    ]
    assert task["due"] == "2026-10-03T09:00:00+09:00"
