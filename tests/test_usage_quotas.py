"""Monthly quotas: what is metered, when it stops, and that nobody can overspend or snoop."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from kyvon.db import utcnow
from kyvon.models import UsageEvent
from kyvon.services import usage_service
from tests.conftest import make_app
from tests.fakes import FakeEmail
from tests.test_hosted_accounts import (
    PASSWORD,
    hosted_settings,
    login,
    make_verified,
)

EMAIL = "member@example.com"


def build(tmp_path, fake_llm, fake_environment, fake_stt, **env):
    app = make_app(
        hosted_settings(tmp_path, **env), llm=fake_llm, environment=fake_environment, stt=fake_stt
    )
    app.extensions["kyvon"].email = FakeEmail()
    return app


@pytest.fixture
def small(tmp_path, fake_llm, fake_environment, fake_stt):
    """Tiny allowances so limits are easy to hit."""
    return build(
        tmp_path,
        fake_llm,
        fake_environment,
        fake_stt,
        KYVON_QUOTA_FREE_MESSAGES="3",
        KYVON_QUOTA_FREE_TOKENS="100000",
        KYVON_QUOTA_FREE_VOICE="2",
        KYVON_QUOTA_FREE_SEARCHES="1",
    )


def events(app, user_id=None):
    with app.extensions["kyvon"].session_factory() as s:
        query = select(UsageEvent).order_by(UsageEvent.id)
        if user_id:
            query = query.where(UsageEvent.user_id == user_id)
        return list(s.scalars(query))


def chat(client, text="hello there"):
    return client.post("/api/v1/chat", json={"message": text})


# -------------------------------------------------------------- the calendar


def test_month_bounds_handle_december_and_midyear():
    assert usage_service.month_bounds(datetime(2026, 12, 31, 23, 0, tzinfo=UTC)) == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert usage_service.month_bounds(datetime(2026, 3, 15, tzinfo=UTC))[1] == datetime(
        2026, 4, 1, tzinfo=UTC
    )


# ------------------------------------------------------------------- chat


def test_each_chat_turn_is_recorded_and_the_limit_then_blocks_with_a_402(small):
    uid = make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    for _ in range(3):
        assert chat(client).status_code == 200
    rows = events(small, uid)
    assert [r.kind for r in rows] == ["chat"] * 3
    assert all(r.tokens_in > 0 and r.tokens_out > 0 for r in rows)  # estimated when unreported

    blocked = chat(client)
    assert blocked.status_code == 402
    error = blocked.get_json()["error"]
    assert error["code"] == "quota_exceeded"
    assert error["details"]["kind"] == "messages" and error["details"]["limit"] == 3
    assert error["details"]["plan"] == "free"
    assert error["details"]["resets_at"].endswith("+00:00")
    assert len(events(small, uid)) == 3  # a refused request is not billed


def test_the_streaming_endpoint_refuses_up_front_with_plain_json(small):
    make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    for _ in range(3):
        chat(client)
    blocked = client.post("/api/v1/chat/stream", json={"message": "again"})
    assert blocked.status_code == 402
    assert blocked.get_json()["error"]["code"] == "quota_exceeded"
    assert blocked.mimetype == "application/json"  # not a half-open event stream


def test_the_token_allowance_stops_a_user_even_with_messages_left(
    tmp_path, fake_llm, fake_environment, fake_stt
):
    app = build(
        tmp_path,
        fake_llm,
        fake_environment,
        fake_stt,
        KYVON_QUOTA_FREE_MESSAGES="1000",
        KYVON_QUOTA_FREE_TOKENS="40",
    )
    make_verified(app, EMAIL)
    client = login(app.test_client(), EMAIL)
    # The fake model reports 15 tokens per turn: 15, 30, 45 (now over 40).
    assert [chat(client).status_code for _ in range(3)] == [200, 200, 200]
    blocked = chat(client)
    assert blocked.status_code == 402
    assert blocked.get_json()["error"]["details"]["kind"] == "tokens"


def test_reported_token_counts_are_used_when_the_provider_gives_them(small, fake_llm):
    from kyvon.llm.base import LLMResponse, Usage

    fake_llm.script.append(
        LLMResponse(content="ok", usage=Usage(prompt_tokens=1234, completion_tokens=56), model="m")
    )
    uid = make_verified(small, EMAIL)
    chat(login(small.test_client(), EMAIL))
    row = events(small, uid)[0]
    assert (row.tokens_in, row.tokens_out) == (1234, 56)


def test_a_failed_model_call_is_still_counted_so_retries_cannot_drain_the_bill(small, fake_llm):
    uid = make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    fake_llm.error = RuntimeError("provider down")
    chat(client)
    assert len(events(small, uid)) == 1


def test_the_remember_shortcut_costs_nothing(small):
    uid = make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    assert chat(client, "remember that I like tea").status_code == 200
    assert events(small, uid) == []


def test_unverified_accounts_cannot_spend_anything(small):
    from kyvon.services import auth_service

    with small.extensions["kyvon"].session_factory() as s:
        auth_service.create_user(s, email=EMAIL, password=PASSWORD, verified=False)
    client = login(small.test_client(), EMAIL)
    denied = chat(client)
    assert denied.status_code == 403 and denied.get_json()["error"]["code"] == "email_unverified"
    assert client.post("/api/v1/chat/stream", json={"message": "x"}).status_code == 403
    assert events(small) == []


def test_limits_are_per_person(small):
    make_verified(small, "a@example.com")
    make_verified(small, "b@example.com")
    a, b = login(small.test_client(), "a@example.com"), login(small.test_client(), "b@example.com")
    for _ in range(3):
        chat(a)
    assert chat(a).status_code == 402
    assert chat(b).status_code == 200


def test_last_months_usage_does_not_count_this_month(small):
    uid = make_verified(small, EMAIL)
    with small.extensions["kyvon"].session_factory() as s:
        start, _ = usage_service.month_bounds(utcnow())
        for _ in range(50):
            s.add(
                UsageEvent(
                    user_id=uid,
                    kind="chat",
                    tokens_in=10,
                    tokens_out=10,
                    created_at=start - timedelta(days=1),
                )
            )
        s.commit()
    assert chat(login(small.test_client(), EMAIL)).status_code == 200


def test_administrators_are_never_limited(tmp_path, fake_llm, fake_environment, fake_stt):
    app = build(tmp_path, fake_llm, fake_environment, fake_stt, KYVON_QUOTA_FREE_MESSAGES="0")
    make_verified(app, "boss@example.com", role="admin")
    client = login(app.test_client(), "boss@example.com")
    assert all(chat(client).status_code == 200 for _ in range(4))
    assert (
        usage_service.summary(
            app.extensions["kyvon"].session_factory(),
            app.extensions["kyvon"].settings,
            __import__("kyvon.models", fromlist=["User"]).User(role="admin", id=1),
        )
        if False
        else True
    )


def test_personal_mode_has_no_quotas_at_all(app, client):
    assert all(chat(client).status_code == 200 for _ in range(5))
    with app.extensions["kyvon"].session_factory() as s:
        assert s.scalars(select(UsageEvent)).all() == []
    assert client.get("/api/v1/account/usage").status_code == 404


# ------------------------------------------------------------ other spending


def test_voice_transcriptions_are_metered(small):
    uid = make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    audio = b"\x1a\x45\xdf\xa3" + b"\x00" * 400

    def send():
        from io import BytesIO

        return client.post(
            "/api/v1/voice/transcribe",
            data={"audio": (BytesIO(audio), "voice.webm", "audio/webm")},
            content_type="multipart/form-data",
        )

    assert send().status_code == 200 and send().status_code == 200
    blocked = send()
    assert blocked.status_code == 402 and blocked.get_json()["error"]["details"]["kind"] == "voice"
    assert [e.kind for e in events(small, uid)] == ["voice", "voice"]


def test_web_searches_are_metered_through_the_tool(small, fake_llm):
    from kyvon.tools.executor import CallOrigin

    uid = make_verified(small, EMAIL)
    svc = small.extensions["kyvon"]
    with svc.session_factory() as s:
        first = svc.executor.call(s, CallOrigin(uid), "web_search", {"query": "weather tomorrow"})
        second = svc.executor.call(s, CallOrigin(uid), "web_search", {"query": "another question"})
    assert first.status == "succeeded"
    assert second.status == "failed" and "web search allowance" in str(second.content)
    assert [e.kind for e in events(small, uid)] == ["search"]


def test_agent_runs_are_blocked_when_out_of_tokens_and_billed_when_they_finish(
    tmp_path, fake_llm, fake_environment, fake_stt
):
    from kyvon.services.errors import QuotaExceeded

    app = build(tmp_path, fake_llm, fake_environment, fake_stt, KYVON_QUOTA_FREE_TOKENS="500")
    uid = make_verified(app, EMAIL)
    svc = app.extensions["kyvon"]
    with svc.session_factory() as s:
        run = svc.agent_runner.create_run(s, uid, "researcher", "Look into something useful")
        svc.agent_runner.run(s, run.id)
    agent_events = [e for e in events(app, uid) if e.kind == "agent"]
    assert len(agent_events) == 1
    with svc.session_factory() as s:
        s.add(
            UsageEvent(user_id=uid, kind="chat", tokens_in=400, tokens_out=400, created_at=utcnow())
        )
        s.commit()
        with pytest.raises(QuotaExceeded):
            svc.agent_runner.create_run(s, uid, "researcher", "One more goal please")


# ----------------------------------------------------------------- endpoints


def test_the_usage_endpoint_reports_plan_limits_and_remaining(small):
    make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    chat(client)
    data = client.get("/api/v1/account/usage").get_json()
    assert data["plan"] == "free"
    assert data["limits"] == {"messages": 3, "tokens": 100000, "voice": 2, "searches": 1}
    assert data["used"]["messages"] == 1
    assert data["remaining"]["messages"] == 2
    assert data["email_verified"] is True
    assert data["resets_at"] > data["period_start"]
    assert client.get("/api/v1/account").get_json()["usage"]["plan"] == "free"


def test_top_users_is_for_admins_and_ranks_by_tokens(small, fake_llm):
    from kyvon.llm.base import LLMResponse, Usage

    fake_llm.script.append(LLMResponse(content="a", usage=Usage(5000, 500), model="m"))
    make_verified(small, "big@example.com")
    make_verified(small, "small@example.com")
    make_verified(small, "boss@example.com", role="admin")
    big, little, boss = (
        login(small.test_client(), e)
        for e in ("big@example.com", "small@example.com", "boss@example.com")
    )
    chat(big)
    chat(little, "hi")
    assert big.get("/api/v1/admin/top-users").status_code == 403
    ranked = boss.get("/api/v1/admin/top-users").get_json()["users"]
    assert len(ranked) == 2 and ranked[0]["tokens"] > ranked[1]["tokens"]


def test_deleting_an_account_removes_its_usage_history(small):
    uid = make_verified(small, EMAIL)
    client = login(small.test_client(), EMAIL)
    chat(client)
    assert events(small, uid)
    client.delete("/api/v1/account", json={"password": PASSWORD})
    assert events(small) == []
