"""Automation: schedules, runner, scheduler, tools, API and notifications."""

import json
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from kyvon.automation.runner import MAX_CONSECUTIVE_FAILURES, AutomationRunner
from kyvon.automation.scheduler import Scheduler
from kyvon.automation.schedules import describe, next_run, parse_time, validate_schedule
from kyvon.llm.base import LLMResponse, ToolCall
from kyvon.models import Automation, AutomationRun, Conversation, Notification, User
from kyvon.services import auth_service
from kyvon.services.automation_service import AutomationService
from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure

CHI = ZoneInfo("America/Chicago")
UTC_NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # Thursday, 10:00 in Chicago


# ------------------------------------------------------------ schedules


@pytest.mark.parametrize("value", ["08:00", "00:00", "23:59"])
def test_parse_time_ok(value):
    assert parse_time(value).strftime("%H:%M") == value


@pytest.mark.parametrize("value", ["8:00", "24:00", "12:60", "noon", "", "08:00:00"])
def test_parse_time_bad(value):
    with pytest.raises(ValidationFailure):
        parse_time(value)


def test_validate_normalises():
    assert validate_schedule(
        {"type": "weekly", "days": ["Sun", "MON", "sunday"], "time": "18:00"}, CHI
    ) == {
        "type": "weekly",
        "days": ["mon", "sun"],
        "time": "18:00",
    }
    assert (
        validate_schedule({"type": "once", "at": "2026-10-03T08:00:00-05:00"}, CHI)["at"]
        == "2026-10-03T08:00"
    )
    assert (
        validate_schedule({"type": "once", "at": "2026-10-03T13:00:00+00:00"}, CHI)["at"]
        == "2026-10-03T08:00"
    )


@pytest.mark.parametrize(
    "spec",
    [
        None,
        {},
        {"type": "hourly"},
        {"type": "once", "at": "tomorrow"},
        {"type": "daily"},
        {"type": "weekly", "days": [], "time": "08:00"},
        {"type": "weekly", "days": ["funday"], "time": "08:00"},
        {"type": "monthly", "day": 0, "time": "08:00"},
        {"type": "monthly", "day": 32, "time": "08:00"},
        {"type": "interval", "minutes": 5},
        {"type": "interval", "minutes": 0},
        {"type": "interval", "minutes": 10**6},
        {"type": "interval", "minutes": "60"},
        {"type": "interval", "minutes": True},
    ],
)
def test_invalid_schedules(spec):
    with pytest.raises(ValidationFailure):
        validate_schedule(spec, CHI)


def local(dt):
    return dt.astimezone(CHI).strftime("%Y-%m-%d %H:%M")


def test_daily_next_run():
    spec = {"type": "daily", "time": "08:00"}
    assert local(next_run(spec, CHI, UTC_NOW)) == "2026-10-02 08:00"  # 10:00 already passed today
    early = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)  # 06:00 local
    assert local(next_run(spec, CHI, early)) == "2026-10-01 08:00"
    exactly = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)  # exactly 08:00 local: strictly after
    assert local(next_run(spec, CHI, exactly)) == "2026-10-02 08:00"


def test_weekly_next_run():
    spec = {"type": "weekly", "days": ["sun", "wed"], "time": "18:00"}
    assert local(next_run(spec, CHI, UTC_NOW)) == "2026-10-04 18:00"  # Thursday -> Sunday
    sunday_noon = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
    assert local(next_run(spec, CHI, sunday_noon)) == "2026-10-04 18:00"
    sunday_evening = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)  # 18:30 local
    assert local(next_run(spec, CHI, sunday_evening)) == "2026-10-07 18:00"  # Wednesday


def test_monthly_next_run_and_clamping():
    spec = {"type": "monthly", "day": 31, "time": "09:00"}
    assert local(next_run(spec, CHI, UTC_NOW)) == "2026-10-31 09:00"
    after_oct = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    assert local(next_run(spec, CHI, after_oct)) == "2026-11-30 09:00"  # November has 30 days
    feb = datetime(2027, 2, 1, 12, 0, tzinfo=UTC)
    assert local(next_run(spec, CHI, feb)) == "2027-02-28 09:00"


def test_once_and_interval():
    assert (
        local(next_run({"type": "once", "at": "2026-10-03T08:00"}, CHI, UTC_NOW))
        == "2026-10-03 08:00"
    )
    assert next_run({"type": "once", "at": "2026-09-01T08:00"}, CHI, UTC_NOW) is None
    assert next_run({"type": "interval", "minutes": 90}, CHI, UTC_NOW) == UTC_NOW + timedelta(
        minutes=90
    )


def test_wall_clock_survives_daylight_saving():
    spec = {"type": "daily", "time": "08:00"}
    before = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)  # the clocks fall back overnight
    first = next_run(spec, CHI, before)
    second = next_run(spec, CHI, first)
    assert local(first) == "2026-10-31 08:00" and local(second) == "2026-11-01 08:00"
    assert second - first == timedelta(hours=25)  # one 25-hour day, still 8 AM local


def test_describe():
    assert describe({"type": "daily", "time": "08:00"}) == "every day at 08:00"
    assert describe({"type": "weekly", "days": ["sun"], "time": "18:00"}) == "every sun at 18:00"
    assert describe({"type": "interval", "minutes": 120}) == "every 2 hours"
    assert describe({"type": "interval", "minutes": 45}) == "every 45 minutes"


# ------------------------------------------------------------ fixtures


@pytest.fixture
def svc(app):
    return app.extensions["kyvon"]


@pytest.fixture
def session(svc):
    with svc.session_factory() as s:
        yield s


class Clock:
    def __init__(self, start=UTC_NOW):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock(svc):
    c = Clock()
    svc.automation_runner = AutomationRunner(svc, now=c)
    svc.scheduler = Scheduler(svc, now=c)
    return c


@pytest.fixture
def automations(session, owner, clock):
    return AutomationService(session, owner.id, timezone="America/Chicago", now=clock)


def make(automations, name="Morning check", kind="reminder", schedule=None, **kw):
    schedule = schedule or {"type": "daily", "time": "08:00"}
    if kind == "reminder":
        kw.setdefault("text", "Take your vitamins")
    else:
        kw.setdefault("prompt", "Check my calendar and tell me what's important")
    return automations.create(name, kind, schedule, **kw)


def notes(session):
    return list(session.scalars(select(Notification).order_by(Notification.id)))


# ------------------------------------------------------------ service


def test_create_computes_first_run_in_the_automations_timezone(automations):
    a = make(automations)
    assert local(a.next_run_at) == "2026-10-02 08:00" and a.timezone == "America/Chicago"
    assert a.enabled and a.run_count == 0 and a.source == "user"


def test_validation(automations):
    with pytest.raises(ValidationFailure, match="name"):
        make(automations, name=" ")
    with pytest.raises(ValidationFailure, match="Kind"):
        make(automations, kind="script")
    with pytest.raises(ValidationFailure, match="some text"):
        automations.create("x", "reminder", {"type": "daily", "time": "08:00"}, text="  ")
    with pytest.raises(ValidationFailure, match="prompt"):
        automations.create("x", "prompt", {"type": "daily", "time": "08:00"})
    with pytest.raises(ValidationFailure, match="already passed"):
        make(automations, schedule={"type": "once", "at": "2026-01-01T08:00"})
    with pytest.raises(ValidationFailure, match="limited"):
        make(automations, prompt="x" * 1001, kind="prompt")


def test_per_user_limit(session, owner, clock):
    limited = AutomationService(session, owner.id, max_automations=2, timezone="UTC", now=clock)
    make(limited, name="a")
    make(limited, name="b")
    with pytest.raises(ConflictError, match="at most 2"):
        make(limited, name="c")


def test_update_and_enable_disable(automations):
    a = make(automations)
    automations.update(a.id, schedule={"type": "daily", "time": "09:30"}, name="Later")
    assert a.name == "Later" and local(a.next_run_at) == "2026-10-02 09:30"
    automations.update(a.id, enabled=False)
    assert a.enabled is False and a.next_run_at is None and a.disabled_reason == "Turned off"
    automations.update(a.id, enabled=True)
    assert a.enabled and a.next_run_at is not None and a.disabled_reason is None


def test_reenabling_a_finished_one_time_automation_is_refused(automations):
    a = make(automations, schedule={"type": "once", "at": "2026-10-01T12:00"})
    a.enabled, a.next_run_at = False, None
    automations.update(a.id, name="renamed")
    with pytest.raises(ValidationFailure, match="passed"):
        automations.update(a.id, enabled=True, schedule={"type": "once", "at": "2026-01-01T12:00"})


def test_isolation(session, owner, clock):
    other = User(username="stranger", password_hash="x")
    session.add(other)
    session.commit()
    mine = make(AutomationService(session, owner.id, timezone="UTC", now=clock))
    theirs = AutomationService(session, other.id, timezone="UTC", now=clock)
    assert theirs.list() == []
    for action in (theirs.get, theirs.delete, theirs.runs):
        with pytest.raises(NotFoundError):
            action(mine.id)
    with pytest.raises(NotFoundError):
        theirs.update(mine.id, enabled=False)


# ------------------------------------------------------------ runner


def run(svc, session, automation, **kw):
    return svc.automation_runner.execute(session, automation.id, **kw)


def test_reminder_creates_a_notification(svc, session, automations, clock):
    a = make(automations)
    result = run(svc, session, a, scheduled_for=a.next_run_at)
    assert result.status == "succeeded" and result.result == "Take your vitamins"
    (note,) = notes(session)
    assert (note.title, note.body, note.source, note.automation_id) == (
        "Morning check",
        "Take your vitamins",
        "automation",
        a.id,
    )
    assert a.run_count == 1 and a.last_status == "succeeded" and a.failure_count == 0
    assert local(a.next_run_at) == "2026-10-03 08:00"


def test_prompt_runs_the_assistant_in_its_own_conversation(svc, session, automations, fake_llm):
    fake_llm.script = ["Nothing urgent today; the dentist is at 2 PM."]
    a = make(automations, kind="prompt")
    result = run(svc, session, a, scheduled_for=a.next_run_at)
    assert result.status == "succeeded"
    (note,) = notes(session)
    assert note.body == "Nothing urgent today; the dentist is at 2 PM." and note.conversation_id
    conversation = session.get(Conversation, note.conversation_id)
    assert conversation.title == "Automation: Morning check"
    sent = fake_llm.calls[0]["messages"][-1]["content"]
    assert sent.startswith("[Automated run of 'Morning check']") and "calendar" in sent
    assert a.payload["conversation_id"] == conversation.id
    fake_llm.script = ["Second answer."]
    run(svc, session, a, scheduled_for=a.next_run_at)
    assert session.query(Conversation).count() == 1  # the same conversation is reused


def test_scheduled_prompt_cannot_act_without_approval(svc, session, automations, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[ToolCall("c1", "conversation_delete", json.dumps({"conversation_id": 1}))]
        ),
        "I've asked for approval.",
    ]
    a = make(automations, kind="prompt", prompt="clean up my old chats")
    run(svc, session, a, scheduled_for=a.next_run_at)
    (note,) = notes(session)
    assert "1 action(s) are waiting for your approval" in note.body
    from kyvon.models import ToolRun

    assert session.scalar(select(ToolRun.status)) == "pending_confirmation"


def test_prompt_text_cannot_trigger_memory_shortcuts(svc, session, automations, fake_llm):
    a = make(automations, kind="prompt", prompt="remember to water the plants")
    run(svc, session, a, scheduled_for=a.next_run_at)
    from kyvon.models import Memory

    assert session.query(Memory).count() == 0 and fake_llm.calls  # went to the model instead


def test_failures_retry_with_backoff_then_disable(svc, session, automations, fake_llm, clock):
    fake_llm.error = RuntimeError("model down")
    a = make(automations, kind="prompt")
    first = run(svc, session, a, scheduled_for=a.next_run_at)
    assert first.status == "failed" and "model down" in first.error
    assert a.failure_count == 1 and a.enabled and a.next_run_at == clock() + timedelta(minutes=5)

    clock.advance(minutes=5)
    run(svc, session, a, triggered_by="retry", scheduled_for=a.next_run_at)
    assert a.failure_count == 2 and a.next_run_at == clock() + timedelta(minutes=15)

    clock.advance(minutes=15)
    run(svc, session, a, triggered_by="retry", scheduled_for=a.next_run_at)
    assert (
        a.failure_count == MAX_CONSECUTIVE_FAILURES and a.enabled is False and a.next_run_at is None
    )
    assert "3 failures in a row" in a.disabled_reason
    (note,) = notes(session)
    assert note.source == "system" and "turned off" in note.title.lower()
    assert session.query(AutomationRun).filter_by(status="failed").count() == 3


def test_success_resets_the_failure_count(svc, session, automations, fake_llm, clock):
    a = make(automations, kind="prompt")
    fake_llm.error = RuntimeError("down")
    run(svc, session, a, scheduled_for=a.next_run_at)
    fake_llm.error = None
    clock.advance(minutes=5)
    run(svc, session, a, triggered_by="retry", scheduled_for=a.next_run_at)
    assert a.failure_count == 0 and local(a.next_run_at) == "2026-10-02 08:00"


def test_one_time_automation_completes(svc, session, automations, clock):
    a = make(automations, schedule={"type": "once", "at": "2026-10-01T12:00"})
    clock.t = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)
    run(svc, session, a, scheduled_for=datetime(2026, 10, 1, 17, 0, tzinfo=UTC))
    assert a.enabled is False and a.next_run_at is None and a.disabled_reason == "Completed"


def test_manual_run_does_not_change_the_schedule(svc, session, automations, fake_llm):
    a = make(automations)
    planned = a.next_run_at
    result = run(svc, session, a, triggered_by="manual")
    assert result.status == "succeeded" and a.next_run_at == planned and a.run_count == 1


def test_manual_failure_does_not_disable(svc, session, automations, fake_llm):
    a = make(automations, kind="prompt")
    fake_llm.error = RuntimeError("down")
    for _ in range(5):
        run(svc, session, a, triggered_by="manual")
    assert a.enabled and a.next_run_at is not None


def test_missed_runs_are_skipped_after_the_grace_period(svc, session, automations, clock):
    a = make(automations)
    late = a.next_run_at
    clock.t = late + timedelta(hours=13)
    result = run(svc, session, a, scheduled_for=late)
    assert result.status == "skipped" and notes(session) == []
    assert a.next_run_at > clock.t and a.run_count == 0


def test_recently_missed_runs_still_fire_once(svc, session, automations, clock):
    a = make(automations)
    late = a.next_run_at
    clock.t = late + timedelta(hours=2)
    assert run(svc, session, a, scheduled_for=late).status == "succeeded"
    assert len(notes(session)) == 1 and a.next_run_at > clock.t


def test_disabled_between_claim_and_run_is_cancelled(svc, session, automations):
    a = make(automations)
    automations.update(a.id, enabled=False)
    assert run(svc, session, a, scheduled_for=UTC_NOW) is None and notes(session) == []


def test_deleted_automation_is_ignored(svc, session):
    assert svc.automation_runner.execute(session, 999) is None


def test_secrets_are_redacted_in_notifications(svc, session, automations):
    a = make(automations, text="the key is gsk_" + "a" * 30)
    run(svc, session, a, scheduled_for=a.next_run_at)
    assert "gsk_aaaa" not in notes(session)[0].body


# ------------------------------------------------------------ scheduler


def test_tick_runs_only_what_is_due(svc, session, automations, clock):
    due = make(automations, name="due", schedule={"type": "once", "at": "2026-10-01T10:30"})
    later = make(automations, name="later")
    off = make(automations, name="off", schedule={"type": "once", "at": "2026-10-01T10:30"})
    automations.update(off.id, enabled=False)
    clock.t = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)  # 11:00 local
    assert svc.scheduler.tick(inline=True) == 1
    session.expire_all()
    assert [n.title for n in notes(session)] == ["due"]
    assert due.enabled is False and later.run_count == 0 and off.run_count == 0
    assert svc.scheduler.tick(inline=True) == 0  # nothing left to do


def test_two_schedulers_cannot_run_the_same_occurrence(svc, session, automations, clock):
    a = make(automations, schedule={"type": "once", "at": "2026-10-01T10:30"})
    clock.t = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
    other = Scheduler(svc, now=clock)
    # Simulate a second process claiming the row first.
    from sqlalchemy import update

    session.execute(update(Automation).where(Automation.id == a.id).values(next_run_at=None))
    session.commit()
    assert other.tick(inline=True) == 0 and svc.scheduler.tick(inline=True) == 0
    assert notes(session) == []


def test_recover_replans_claimed_but_unfinished_automations(svc, session, automations, clock):
    a = make(automations)
    a.next_run_at = None  # claimed, then the process died
    session.commit()
    assert svc.scheduler.recover() == 1
    session.expire_all()
    assert local(a.next_run_at) == "2026-10-02 08:00"


def test_a_crashing_run_replans_the_automation(svc, session, automations, monkeypatch, clock):
    a = make(automations, schedule={"type": "daily", "time": "10:30"})
    clock.t = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)

    def boom(*args, **kwargs):
        raise RuntimeError("worker died")

    monkeypatch.setattr(svc.automation_runner, "execute", boom)
    svc.scheduler.tick(inline=True)
    session.expire_all()
    assert session.get(Automation, a.id).next_run_at is not None  # not stuck in limbo


def test_background_thread_lifecycle(svc, session, owner):
    from sqlalchemy import update

    real_time = AutomationService(session, owner.id, timezone="UTC")
    a = make(real_time, schedule={"type": "interval", "minutes": 15})
    session.execute(
        update(Automation)
        .where(Automation.id == a.id)
        .values(next_run_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    session.commit()
    scheduler = Scheduler(svc, tick_seconds=0.05)  # real clock
    scheduler.start()
    try:
        assert scheduler.running
        deadline = time.time() + 5
        while time.time() < deadline and not session.scalar(select(AutomationRun.id)):
            time.sleep(0.05)
            session.expire_all()
        assert session.scalar(select(AutomationRun.status)) == "succeeded"
    finally:
        scheduler.stop()
    assert not scheduler.running


def test_scheduler_survives_a_failing_tick(svc, monkeypatch):
    scheduler = Scheduler(svc, tick_seconds=0.02)
    calls = {"n": 0}

    def flaky_tick(*a, **k):
        calls["n"] += 1
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(scheduler, "tick", flaky_tick)
    scheduler.start()
    try:
        deadline = time.time() + 3
        while time.time() < deadline and calls["n"] < 3:
            time.sleep(0.02)
    finally:
        scheduler.stop()
    assert calls["n"] >= 3 and "db hiccup" in scheduler.last_error


def test_scheduler_is_not_started_by_the_app_in_tests(svc):
    assert svc.scheduler.running is False and svc.settings.scheduler_enabled is False


# ------------------------------------------------------------ tools (natural language)


def call(call_id, tool, /, **arguments):
    return ToolCall(call_id, tool, json.dumps(arguments))


def ask(client, message, cid=None):
    body = {"message": message, **({"conversation_id": cid} if cid else {})}
    return client.post("/api/v1/chat", json=body).get_json()


@pytest.fixture
def in_chicago(app, owner):
    with app.extensions["kyvon"].session_factory() as s:
        s.get(User, owner.id).settings = {"timezone": "America/Chicago"}
        s.commit()


def approve(client, body):
    (pending,) = body["pending_confirmations"]
    return client.post(f"/api/v1/tool-runs/{pending['id']}/confirm").get_json()["tool_run"], pending


def test_remind_me_tomorrow_at_8am(client, fake_llm, in_chicago):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "automation_create",
                    name="Call mom",
                    kind="reminder",
                    message="Call mom",
                    schedule_type="once",
                    at="2099-10-02T08:00",
                )
            ]
        ),
        "I've asked for your approval to set that reminder.",
    ]
    run_, pending = approve(client, ask(client, "Remind me tomorrow at 8 AM to call mom"))
    assert (
        pending["summary"]
        == 'Create the automation "Call mom": once at 2099-10-02 08:00 — remind you: "Call mom"'
    )
    assert run_["status"] == "succeeded"
    (auto,) = client.get("/api/v1/automations").get_json()["automations"]
    assert (auto["kind"], auto["source"], auto["timezone"]) == (
        "reminder",
        "assistant",
        "America/Chicago",
    )


def test_every_sunday_summarise_my_week(client, fake_llm, in_chicago):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "automation_create",
                    name="Weekly summary",
                    kind="prompt",
                    message="Summarise my upcoming week from my calendar and tasks",
                    schedule_type="weekly",
                    days=["sun"],
                    time="18:00",
                )
            ]
        ),
        "Waiting for approval.",
    ]
    approve(client, ask(client, "Every Sunday, summarize my upcoming week"))
    (auto,) = client.get("/api/v1/automations").get_json()["automations"]
    assert auto["schedule"] == {"type": "weekly", "days": ["sun"], "time": "18:00"}
    assert (
        auto["prompt"].startswith("Summarise my upcoming week")
        and auto["schedule_text"] == "every sun at 18:00"
    )


def test_daily_morning_and_evening_examples(client, fake_llm, in_chicago):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "automation_create",
                    name="Morning brief",
                    kind="prompt",
                    message="Check my calendar and tell me what is important today",
                    schedule_type="daily",
                    time="07:30",
                )
            ]
        ),
        "ok",
        LLMResponse(
            tool_calls=[
                call(
                    "c2",
                    "automation_create",
                    name="Task review",
                    kind="reminder",
                    message="Review your tasks",
                    schedule_type="daily",
                    time="20:00",
                )
            ]
        ),
        "ok",
    ]
    approve(client, ask(client, "Every morning, check my calendar and tell me what's important"))
    approve(client, ask(client, "Every evening, remind me to review my tasks"))
    names = {a["name"] for a in client.get("/api/v1/automations").get_json()["automations"]}
    assert names == {"Morning brief", "Task review"}


def test_nothing_is_scheduled_before_approval(client, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "automation_create",
                    name="X",
                    kind="reminder",
                    message="x",
                    schedule_type="daily",
                    time="08:00",
                )
            ]
        ),
        "waiting",
    ]
    body = ask(client, "remind me daily")
    assert (
        body["pending_confirmations"]
        and client.get("/api/v1/automations").get_json()["automations"] == []
    )
    client.post(f"/api/v1/tool-runs/{body['pending_confirmations'][0]['id']}/reject")
    assert client.get("/api/v1/automations").get_json()["automations"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"schedule_type": "daily"},
        {"schedule_type": "daily", "time": "25:00"},
        {"schedule_type": "weekly", "time": "08:00"},
        {"schedule_type": "once", "at": "2001-01-01T08:00"},
    ],
)
def test_bad_schedules_fail_after_approval_without_creating_anything(client, fake_llm, arguments):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call("c1", "automation_create", name="X", kind="reminder", message="x", **arguments)
            ]
        ),
        "ok",
    ]
    run_, _ = approve(client, ask(client, "schedule something"))
    assert (
        run_["status"] == "failed"
        and client.get("/api/v1/automations").get_json()["automations"] == []
    )


def test_intervals_below_the_floor_are_rejected_at_the_schema(client, fake_llm):
    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call(
                    "c1",
                    "automation_create",
                    name="Spam",
                    kind="reminder",
                    message="x",
                    schedule_type="interval",
                    every_minutes=1,
                )
            ]
        ),
        "ok",
    ]
    body = ask(client, "remind me every minute")
    assert "pending_confirmations" not in body
    told = json.loads(
        [m for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"][0]["content"]
    )
    assert "Invalid arguments" in told["error"]


def test_list_toggle_and_delete_tools(client, fake_llm, session):
    created = client.post(
        "/api/v1/automations",
        json={
            "name": "Vitamins",
            "kind": "reminder",
            "text": "Take vitamins",
            "schedule": {"type": "daily", "time": "08:00"},
        },
    ).get_json()["automation"]
    fake_llm.script = [
        LLMResponse(tool_calls=[call("c1", "automation_list")]),
        "You have one automation.",
    ]
    ask(client, "what automations do I have?")
    listed = json.loads(
        [m for m in fake_llm.calls[-1]["messages"] if m["role"] == "tool"][0]["content"]
    )
    assert listed["data"][0]["name"] == "Vitamins"

    fake_llm.script = [
        LLMResponse(
            tool_calls=[
                call("c2", "automation_set_enabled", automation_id=created["id"], enabled=False)
            ]
        ),
        "Turned off.",
    ]
    ask(client, "pause the vitamins reminder")
    assert (
        client.get(f"/api/v1/automations/{created['id']}").get_json()["automation"]["enabled"]
        is False
    )

    fake_llm.script = [
        LLMResponse(tool_calls=[call("c3", "automation_delete", automation_id=created["id"])]),
        "Waiting.",
    ]
    run_, pending = approve(client, ask(client, "delete the vitamins reminder"))
    assert (
        pending["summary"] == 'Delete the automation "Vitamins"' and run_["status"] == "succeeded"
    )
    assert client.get("/api/v1/automations").get_json()["automations"] == []


# ------------------------------------------------------------ API


def test_api_crud_and_validation(client):
    body = {
        "name": "Standup",
        "kind": "reminder",
        "text": "Standup time",
        "schedule": {"type": "weekly", "days": ["mon", "tue"], "time": "09:00"},
    }
    created = client.post("/api/v1/automations", json=body)
    assert created.status_code == 201
    auto = created.get_json()["automation"]
    assert auto["schedule_text"] == "every mon, tue at 09:00" and auto["next_run_at"]
    url = f"/api/v1/automations/{auto['id']}"
    patched = client.patch(url, json={"enabled": False, "name": "Standup!"}).get_json()[
        "automation"
    ]
    assert (
        patched["enabled"] is False
        and patched["name"] == "Standup!"
        and patched["next_run_at"] is None
    )
    assert client.patch(url, json={"enabled": True}).get_json()["automation"]["next_run_at"]
    assert client.delete(url).status_code == 200 and client.get(url).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {
            "name": "x",
            "kind": "reminder",
            "schedule": {"type": "interval", "minutes": 1},
            "text": "t",
        },
        {"name": "x", "kind": "shell", "schedule": {"type": "daily", "time": "08:00"}, "text": "t"},
        {"name": "x", "kind": "prompt", "schedule": {"type": "daily", "time": "08:00"}},
        {"name": "x", "kind": "reminder", "schedule": "daily", "text": "t"},
    ],
)
def test_api_rejects_bad_automations(client, body):
    assert client.post("/api/v1/automations", json=body).status_code == 400


def test_api_run_now_and_history(client, svc):
    auto = client.post(
        "/api/v1/automations",
        json={
            "name": "Ping",
            "kind": "reminder",
            "text": "ping",
            "schedule": {"type": "daily", "time": "08:00"},
        },
    ).get_json()["automation"]
    assert client.post(f"/api/v1/automations/{auto['id']}/run").status_code == 202
    deadline = time.time() + 5
    runs = []
    while time.time() < deadline and not runs:
        time.sleep(0.05)
        runs = client.get(f"/api/v1/automations/{auto['id']}/runs").get_json()["runs"]
    assert runs[0]["status"] == "succeeded" and runs[0]["triggered_by"] == "manual"
    inbox = client.get("/api/v1/notifications").get_json()
    assert inbox["unread_count"] == 1 and inbox["notifications"][0]["title"] == "Ping"


def test_api_notifications_flow(client, app, owner):
    from kyvon.services.notification_service import NotificationService

    with app.extensions["kyvon"].session_factory() as s:
        service = NotificationService(s, owner.id)
        ids = [service.create(f"note {i}", "body").id for i in range(3)]
    assert client.get("/api/v1/notifications").get_json()["unread_count"] == 3
    assert (
        client.post(f"/api/v1/notifications/{ids[0]}/read").get_json()["notification"]["read"]
        is True
    )
    assert [
        n["title"] for n in client.get("/api/v1/notifications?unread=1").get_json()["notifications"]
    ] == ["note 2", "note 1"]
    assert client.post("/api/v1/notifications/read-all").get_json() == {"marked": 2}
    assert client.get("/api/v1/notifications").get_json()["unread_count"] == 0
    assert client.delete(f"/api/v1/notifications/{ids[1]}").status_code == 200
    assert client.delete(f"/api/v1/notifications/{ids[1]}").status_code == 404
    assert client.get("/api/v1/notifications?limit=x").status_code == 400


def test_api_isolation_and_auth(app, client, anon_client, owner):
    auto = client.post(
        "/api/v1/automations",
        json={
            "name": "Mine",
            "kind": "reminder",
            "text": "t",
            "schedule": {"type": "daily", "time": "08:00"},
        },
    ).get_json()["automation"]
    with app.extensions["kyvon"].session_factory() as s:
        from kyvon.services.notification_service import NotificationService

        note_id = NotificationService(s, owner.id).create("private", "x").id
        other = User(username="stranger", password_hash="x")
        s.add(other)
        s.commit()
        raw, _ = auth_service.issue_token(s, other, name="t", ttl_days=1)
    h = {"Authorization": f"Bearer {raw}"}
    url = f"/api/v1/automations/{auto['id']}"
    for method, path in [
        ("get", url),
        ("patch", url),
        ("delete", url),
        ("post", url + "/run"),
        ("get", url + "/runs"),
        ("post", f"/api/v1/notifications/{note_id}/read"),
        ("delete", f"/api/v1/notifications/{note_id}"),
    ]:
        response = getattr(anon_client, method)(
            path, headers=h, **({"json": {}} if method in ("patch",) else {})
        )
        assert response.status_code == 404, (method, path)
    assert anon_client.get("/api/v1/automations", headers=h).get_json()["automations"] == []
    assert anon_client.get("/api/v1/notifications", headers=h).get_json()["notifications"] == []
    assert anon_client.get("/api/v1/automations").status_code == 401
    assert anon_client.get("/api/v1/notifications").status_code == 401
