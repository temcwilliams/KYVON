"""Conversation service, context builder and the conversation/chat API."""

import json

import pytest

from kyvon.db import Base, make_engine, make_session_factory
from kyvon.models import Conversation, Message, User
from kyvon.services.context_builder import ContextBuilder, ContextLimits, estimate_tokens
from kyvon.services.conversation_service import ConversationService, title_from_text
from kyvon.services.errors import NotFoundError, ValidationFailure
from tests.conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def two_users(session):
    a, b = User(username="a", password_hash="x"), User(username="b", password_hash="x")
    session.add_all([a, b])
    session.commit()
    return a, b


@pytest.fixture
def svc(session, two_users):
    return ConversationService(session, two_users[0].id)


# ------------------------------------------------------------ service


def test_create_list_order_and_titles(svc):
    first = svc.create()
    second = svc.create("Named")
    svc.add_message(first, "user", "bump")  # touching a conversation moves it to the top
    assert [c.id for c in svc.list()] == [first.id, second.id]
    assert second.title == "Named" and second.title_source == "user"


def test_title_from_text():
    assert title_from_text("  hello \n world ") == "hello world"
    assert title_from_text("") == "New conversation"
    assert len(title_from_text("x" * 200)) == 60


def test_rename_and_validation(svc):
    c = svc.create()
    assert svc.rename(c.id, ' "Trip plans" ').title == "Trip plans"
    with pytest.raises(ValidationFailure):
        svc.rename(c.id, "   ")


def test_auto_title_respects_user_title(svc):
    c = svc.create()
    svc.set_auto_title(c, "Generated")
    assert c.title == "Generated"
    svc.rename(c.id, "Mine")
    svc.set_auto_title(c, "Generated again")
    assert c.title == "Mine"


def test_archive_hides_from_default_list(svc):
    c = svc.create("x")
    svc.archive(c.id)
    assert svc.list() == [] and [x.id for x in svc.list(archived=True)] == [c.id]
    svc.archive(c.id, False)
    assert [x.id for x in svc.list()] == [c.id]


def test_delete_removes_messages(svc, session):
    c = svc.create("x")
    svc.add_message(c, "user", "hello")
    svc.delete(c.id)
    assert session.query(Conversation).count() == 0 and session.query(Message).count() == 0
    with pytest.raises(NotFoundError):
        svc.get(c.id)


def test_isolation_between_users(session, two_users):
    a, b = two_users
    mine = ConversationService(session, a.id).create("mine")
    theirs = ConversationService(session, b.id)
    with pytest.raises(NotFoundError):
        theirs.get(mine.id)
    with pytest.raises(NotFoundError):
        theirs.messages(mine.id)
    with pytest.raises(NotFoundError):
        theirs.delete(mine.id)
    with pytest.raises(NotFoundError):
        theirs.rename(mine.id, "hijack")
    assert theirs.list() == []


def test_messages_ordered_and_paged(svc):
    c = svc.create("x")
    for i in range(10):
        svc.add_message(c, "user" if i % 2 == 0 else "assistant", f"m{i}")
    all_rows = svc.messages(c.id)
    assert [m.content for m in all_rows] == [f"m{i}" for i in range(10)]
    newest = svc.messages(c.id, limit=3)
    assert [m.content for m in newest] == ["m7", "m8", "m9"]  # newest page, chronological
    older = svc.messages(c.id, before_id=newest[0].id, limit=3)
    assert [m.content for m in older] == ["m4", "m5", "m6"]
    newer = svc.messages(c.id, after_id=all_rows[6].id)
    assert [m.content for m in newer] == ["m7", "m8", "m9"]


def test_tool_rows_hidden_by_default(svc):
    c = svc.create("x")
    svc.add_message(c, "user", "hi")
    svc.add_message(c, "assistant", "", kind="tool_call", tool_calls=[{"id": "1"}])
    assert len(svc.messages(c.id)) == 1
    assert len(svc.messages(c.id, kinds=("message", "tool_call"))) == 2


# ------------------------------------------------------------ context builder


def fill(svc, conversation, count, size=40):
    for i in range(count):
        svc.add_message(conversation, "user" if i % 2 == 0 else "assistant", f"{i}:" + "x" * size)


def build(session, conversation, **limits):
    return ContextBuilder(session, ContextLimits(**limits)).build(
        conversation, memory="- fact", environment="ENV"
    )


def test_short_conversation_is_fully_included(svc, session):
    c = svc.create()
    svc.add_message(c, "user", "hello")
    ctx = build(session, c)
    assert [m["role"] for m in ctx.messages] == ["system", "user"]
    assert ctx.dropped_count == 0 and "- fact" in ctx.messages[0]["content"]


def test_message_count_limit_keeps_newest(svc, session):
    c = svc.create()
    fill(svc, c, 11)  # ends with a user message (index 10)
    ctx = build(session, c, max_messages=4)
    history = ctx.messages[1:]
    assert len(history) <= 4
    assert history[-1]["content"].startswith("10:")
    assert history[0]["role"] == "user"  # never starts with an assistant turn
    assert ctx.dropped_count > 0


def test_token_budget_limits_history(svc, session):
    c = svc.create()
    fill(svc, c, 41, size=2000)
    ctx = build(session, c, max_tokens=4000, reserve_tokens=500, max_messages=100)
    assert 0 < len(ctx.messages) - 1 < 41
    assert ctx.messages[-1]["content"].startswith("40:")
    body = sum(estimate_tokens(m["content"]) for m in ctx.messages)
    assert body <= 4000


def test_oversized_newest_message_is_truncated_not_dropped(svc, session):
    c = svc.create()
    svc.add_message(c, "user", "y" * 100_000)
    ctx = build(session, c, max_tokens=2000, reserve_tokens=500)
    assert ctx.messages[-1]["role"] == "user"
    assert "truncated" in ctx.messages[-1]["content"]
    assert len(ctx.messages[-1]["content"]) < 10_000


def test_errors_partials_and_tool_rows_excluded(svc, session):
    c = svc.create()
    svc.add_message(c, "user", "q1")
    svc.add_message(c, "assistant", "boom", status="error")
    svc.add_message(c, "assistant", "half", status="partial")
    svc.add_message(c, "assistant", "", kind="tool_call")
    svc.add_message(c, "user", "q2")
    ctx = build(session, c)
    assert [m["content"] for m in ctx.messages[1:]] == ["q1", "q2"]


def test_event_messages_become_system_notes(svc, session):
    c = svc.create()
    svc.add_message(c, "user", "delete it")
    svc.add_message(c, "system", "User confirmed: delete task", kind="event")
    svc.add_message(c, "user", "thanks")
    ctx = build(session, c)
    assert ctx.messages[2] == {"role": "system", "content": "Note: User confirmed: delete task"}


def test_summary_only_used_when_history_was_cut(svc, session):
    c = svc.create()
    c.summary = "We planned a trip."
    session.commit()
    fill(svc, c, 3)
    assert "We planned a trip." not in build(session, c, max_messages=50).messages[0]["content"]
    fill(svc, c, 30)
    ctx = build(session, c, max_messages=4)
    assert ctx.summary_used and "We planned a trip." in ctx.messages[0]["content"]


def test_context_never_includes_other_conversations(svc, session):
    a, b = svc.create(), svc.create()
    svc.add_message(a, "user", "secret in A")
    svc.add_message(b, "user", "hello from B")
    assert "secret in A" not in json.dumps(build(session, b).messages)


# ------------------------------------------------------------ API


def chat(client, message, conversation_id=None):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post("/api/v1/chat", json=body)


def test_api_multiple_conversations_are_independent(client, fake_llm):
    a = chat(client, "topic alpha").get_json()["conversation_id"]
    b = chat(client, "topic beta").get_json()["conversation_id"]
    assert a != b
    chat(client, "more alpha", a)
    history = [m["content"] for m in fake_llm.calls[-1]["messages"][1:]]
    assert "topic alpha" in history and "topic beta" not in history

    listed = client.get("/api/v1/conversations").get_json()["conversations"]
    assert [c["id"] for c in listed] == [a, b]  # most recently active first
    assert listed[0]["message_count"] == 4 and listed[0]["title"] == "topic alpha"


def test_api_message_history_and_ordering(client):
    cid = chat(client, "one").get_json()["conversation_id"]
    chat(client, "two", cid)
    messages = client.get(f"/api/v1/conversations/{cid}/messages").get_json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "one"),
        ("assistant", "fake reply"),
        ("user", "two"),
        ("assistant", "fake reply"),
    ]
    assert messages == sorted(messages, key=lambda m: m["id"])
    assert messages[1]["model"] and messages[1]["tokens_in"] == 10


def test_api_paging(client):
    cid = chat(client, "m0").get_json()["conversation_id"]
    for i in range(1, 5):
        chat(client, f"m{i}", cid)
    page = client.get(f"/api/v1/conversations/{cid}/messages?limit=4").get_json()["messages"]
    older = client.get(
        f"/api/v1/conversations/{cid}/messages?limit=4&before_id={page[0]['id']}"
    ).get_json()["messages"]
    assert len(page) == 4 and len(older) == 4 and older[-1]["id"] < page[0]["id"]


def test_api_rename_archive_delete(client):
    cid = chat(client, "hello").get_json()["conversation_id"]
    url = f"/api/v1/conversations/{cid}"
    assert (
        client.patch(url, json={"title": "Renamed"}).get_json()["conversation"]["title"]
        == "Renamed"
    )
    assert client.patch(url, json={"archived": True}).get_json()["conversation"]["archived"]
    assert client.get("/api/v1/conversations").get_json()["conversations"] == []
    archived = client.get("/api/v1/conversations?archived=1").get_json()["conversations"]
    assert [c["id"] for c in archived] == [cid]
    assert client.delete(url).status_code == 200
    assert client.get(url).status_code == 404
    assert client.get(url + "/messages").status_code == 404


def test_api_create_empty_conversation(client):
    response = client.post("/api/v1/conversations", json={"title": "Blank"})
    assert response.status_code == 201
    cid = response.get_json()["conversation"]["id"]
    assert client.get(f"/api/v1/conversations/{cid}/messages").get_json() == {"messages": []}


def test_api_conversation_isolation_between_users(app, client, anon_client):
    from kyvon.services import auth_service

    cid = chat(client, "private").get_json()["conversation_id"]
    with app.extensions["kyvon"].session_factory() as s:
        stranger = User(username="stranger", password_hash="x")
        s.add(stranger)
        s.commit()
        raw, _ = auth_service.issue_token(s, stranger, name="t", ttl_days=1)
    headers = {"Authorization": f"Bearer {raw}"}
    base = f"/api/v1/conversations/{cid}"
    assert anon_client.get(base, headers=headers).status_code == 404
    assert anon_client.get(base + "/messages", headers=headers).status_code == 404
    assert anon_client.patch(base, json={"title": "x"}, headers=headers).status_code == 404
    assert anon_client.delete(base, headers=headers).status_code == 404
    assert (
        anon_client.post(
            "/api/v1/chat", json={"message": "hi", "conversation_id": cid}, headers=headers
        ).status_code
        == 404
    )
    assert anon_client.get("/api/v1/conversations", headers=headers).get_json() == {
        "conversations": []
    }
    assert client.get(base).status_code == 200  # the owner still has it


def test_api_unknown_conversation_id_is_404(client):
    assert chat(client, "hi", 999).status_code == 404


def test_api_bad_paging_argument(client):
    assert client.get("/api/v1/conversations?limit=abc").status_code == 400


def test_api_failed_llm_call_is_reported_and_recorded(client, fake_llm):
    fake_llm.error = RuntimeError("model down")
    response = chat(client, "hello")
    assert response.status_code == 500
    fake_llm.error = None
    listed = client.get("/api/v1/conversations").get_json()["conversations"]
    messages = client.get(f"/api/v1/conversations/{listed[0]['id']}/messages").get_json()[
        "messages"
    ]
    assert [(m["role"], m["status"]) for m in messages] == [
        ("user", "complete"),
        ("assistant", "error"),
    ]


def test_api_long_conversation_stays_within_limits(client, fake_llm):
    cid = chat(client, "start").get_json()["conversation_id"]
    for i in range(60):
        chat(client, f"message {i} " + "word " * 100, cid)
    last = [c for c in fake_llm.calls if c["kind"] == "stream"][-1]["messages"]
    assert len(last) <= 41  # system + max 40 history messages
    assert last[-1]["content"].startswith("message 59")
    total = client.get(f"/api/v1/conversations/{cid}").get_json()["conversation"]["message_count"]
    assert total == 122  # nothing is deleted from the database


# ------------------------------------------------------------ streaming API


def parse_sse(data: str):
    events = []
    for block in data.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_stream_endpoint_sends_events_and_persists(client, fake_llm):
    fake_llm.reply = "streaming works well"
    response = client.post("/api/v1/chat/stream", json={"message": "go"})
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["X-Accel-Buffering"] == "no"
    events = parse_sse(response.get_data(as_text=True))
    assert events[0][0] == "start" and events[-1][0] == "done"
    assert (
        "".join(e["text"] for kind, e in events if kind == "delta").strip()
        == "streaming works well"
    )
    cid = events[0][1]["conversation"]["id"]
    saved = client.get(f"/api/v1/conversations/{cid}/messages").get_json()["messages"]
    assert saved[-1]["content"] == "streaming works well" and saved[-1]["status"] == "complete"
    assert events[-1][1]["message"]["id"] == saved[-1]["id"]


def test_stream_validation_errors_are_plain_json(client):
    response = client.post("/api/v1/chat/stream", json={"message": "  "})
    assert response.status_code == 400 and response.is_json
    assert (
        client.post("/api/v1/chat/stream", json={"message": "x", "conversation_id": 99}).status_code
        == 404
    )


def test_stream_failure_emits_error_event_and_saves_it(client, fake_llm):
    fake_llm.reply = "alpha beta gamma delta"
    fake_llm.stream_error_after = 2
    events = parse_sse(
        client.post("/api/v1/chat/stream", json={"message": "go"}).get_data(as_text=True)
    )
    assert events[-1][0] == "error" and "stream broke" in events[-1][1]["message"]
    cid = events[0][1]["conversation"]["id"]
    saved = client.get(f"/api/v1/conversations/{cid}/messages").get_json()["messages"]
    assert saved[-1]["status"] == "error" and saved[-1]["content"].startswith("alpha beta")


def test_stream_requires_auth(anon_client, owner):
    assert anon_client.post("/api/v1/chat/stream", json={"message": "x"}).status_code == 401
    assert TEST_USERNAME and TEST_PASSWORD


def test_client_disconnect_mid_stream_keeps_partial_message(client, fake_llm):
    fake_llm.reply = "one two three four five six"
    response = client.post("/api/v1/chat/stream", json={"message": "go"}, buffered=False)
    iterator = iter(response.response)
    next(iterator)  # start
    next(iterator)  # first delta
    response.close()  # the browser navigated away / lost the connection
    listed = client.get("/api/v1/conversations").get_json()["conversations"]
    saved = client.get(f"/api/v1/conversations/{listed[0]['id']}/messages").get_json()["messages"]
    assert saved[-1]["role"] == "assistant"
    assert saved[-1]["status"] == "partial" and saved[-1]["content"].strip() == "one"
