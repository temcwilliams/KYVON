"""ChatService: routing, persistence, streaming and failure behaviour."""

import pytest

from kyvon.config import Settings
from kyvon.db import Base, make_engine, make_session_factory
from kyvon.llm.base import LLMResponse, Usage
from kyvon.models import Message, User
from kyvon.services.chat_service import ChatFailed, ChatInputError, ChatService
from kyvon.services.conversation_service import ConversationService
from kyvon.services.errors import NotFoundError
from kyvon.services.memory_service import MemoryService
from tests.fakes import FakeLLM


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def user(session):
    u = User(username="owner", password_hash="x")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def make_chat(session, llm):
    def build(user, **overrides):
        settings = Settings.from_env(
            {"GROQ_API_KEY": "k", "KYVON_AUTO_TITLE_LLM": "false", **overrides.pop("env", {})}
        )
        return ChatService(
            session=session,
            settings=settings,
            llm=llm,
            conversations=ConversationService(session, user.id),
            memory=MemoryService(session, user.id),
            environment_text=overrides.pop("environment_text", lambda: "ENV TEXT"),
            **overrides,
        )

    return build


@pytest.fixture
def chat(make_chat, user):
    return make_chat(user)


def rows(session, conversation_id):
    return list(
        session.query(Message).filter_by(conversation_id=conversation_id).order_by(Message.id)
    )


# ------------------------------------------------------------ basic turn


def test_reply_creates_conversation_and_persists_both_messages(chat, session):
    result = chat.reply("hello there")
    assert result.message["content"] == "fake reply"
    assert result.conversation["title"] == "hello there"
    saved = rows(session, result.conversation["id"])
    assert [(m.role, m.content, m.status) for m in saved] == [
        ("user", "hello there", "complete"),
        ("assistant", "fake reply", "complete"),
    ]


def test_model_receives_system_prompt_and_history(chat, llm):
    first = chat.reply("my name is Sam")
    chat.reply("what is my name?", first.conversation["id"])
    messages = llm.calls[-1]["messages"]
    assert messages[0]["role"] == "system" and "You are KYVON" in messages[0]["content"]
    assert [(m["role"], m["content"]) for m in messages[1:]] == [
        ("user", "my name is Sam"),
        ("assistant", "fake reply"),
        ("user", "what is my name?"),
    ]
    assert llm.calls[-1]["model"] == "openai/gpt-oss-120b"
    assert llm.calls[-1]["temperature"] == 0.7 and llm.calls[-1]["max_tokens"] == 1500


def test_environment_text_is_temporary_context(chat, llm, session):
    result = chat.reply("hi")
    assert "ENV TEXT" in llm.calls[0]["messages"][0]["content"]
    assert all("ENV TEXT" not in m.content for m in rows(session, result.conversation["id"]))


def test_relevant_memory_is_injected_and_irrelevant_is_not(chat, llm, user, session):
    memory = MemoryService(session, user.id)
    memory.add("my dog is named Rex")
    memory.add("I work at a bakery")
    chat.reply("what is my dog called?")
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "- my dog is named Rex" in prompt
    assert "bakery" not in prompt


def test_usage_and_model_metadata_saved(chat, llm, session):
    llm.script = [LLMResponse(content="ok", usage=Usage(123, 45), model="model-x")]
    result = chat.reply("hi")
    row = session.get(Message, result.message["id"])
    assert (row.tokens_in, row.tokens_out, row.model) == (123, 45, "model-x")


def test_blank_message_rejected(chat):
    with pytest.raises(ChatInputError):
        chat.reply("   ")


def test_message_is_stripped(chat, llm):
    chat.reply("  hi  ")
    assert llm.calls[0]["messages"][-1]["content"] == "hi"


# ------------------------------------------------------------ shortcuts


def test_memory_shortcut_saves_without_model(chat, llm, user, session):
    result = chat.reply("remember my dog is Rex")
    assert result.message["content"] == "Understood. I have saved that to my memory."
    assert result.flags == {"memory_saved": True}
    assert llm.calls == []
    assert [m["memory"] for m in MemoryService(session, user.id).all()] == ["my dog is Rex"]
    assert len(rows(session, result.conversation["id"])) == 2


def test_remember_that_no_longer_keeps_the_word_that(chat, user, session):
    chat.reply("remember that I am tall")
    assert MemoryService(session, user.id).all()[0]["memory"] == "I am tall"


@pytest.mark.parametrize("phrase", ["don't forget that ", "keep in mind that "])
def test_other_shortcuts(chat, user, session, phrase):
    assert chat.reply(phrase + "milk").flags == {"memory_saved": True}


def test_bare_remember_goes_to_model(chat, llm):
    chat.reply("remember")
    assert len(llm.calls) == 1


def test_web_uses_web_model(chat, llm):
    result = chat.reply("web latest python")
    assert result.flags == {"web": True}
    (call,) = llm.calls
    assert call["kind"] == "complete" and call["model"] == "groq/compound"
    assert call["temperature"] is None and call["max_tokens"] == 1500
    assert call["messages"][1]["content"] == "latest python"


def test_bare_web_goes_to_main_model(chat, llm):
    chat.reply("web")
    assert llm.calls[0]["model"] == "openai/gpt-oss-120b"


# ------------------------------------------------------------ failures


def test_llm_failure_persists_an_error_row(chat, llm, session):
    llm.error = RuntimeError("boom")
    with pytest.raises(ChatFailed, match="boom") as info:
        chat.reply("hi")
    saved = rows(session, info.value.conversation_id)
    assert [m.role for m in saved] == ["user", "assistant"]
    assert saved[1].status == "error" and saved[1].content == "boom"


def test_failed_reply_is_not_sent_back_to_the_model(chat, llm):
    llm.error = RuntimeError("boom")
    with pytest.raises(ChatFailed) as info:
        chat.reply("first")
    llm.error = None
    chat.reply("second", info.value.conversation_id)
    history = [(m["role"], m["content"]) for m in llm.calls[-1]["messages"][1:]]
    assert history == [("user", "first"), ("user", "second")]


def test_web_failure_persists_error(chat, llm, session):
    llm.error = RuntimeError("search down")
    with pytest.raises(ChatFailed):
        chat.reply("web something")
    assert session.query(Message).filter_by(status="error").count() == 1


# ------------------------------------------------------------ streaming


def test_stream_events_in_order(chat):
    events = list(chat.turn("stream please"))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert set(kinds[1:-1]) == {"delta"}
    assert "".join(e["text"] for e in events if e["type"] == "delta").strip() == "fake reply"
    assert events[0]["user_message"]["content"] == "stream please"


def test_stream_error_midway_is_persisted(chat, llm, session):
    llm.reply = "one two three four"
    llm.stream_error_after = 2
    events = list(chat.turn("go"))
    assert events[-1]["type"] == "error" and "stream broke" in events[-1]["message"]
    saved = rows(session, events[0]["conversation"]["id"])
    assert saved[-1].status == "error"
    assert saved[-1].content.startswith("one two")  # the partial text is kept


def test_client_disconnect_saves_partial_text(chat, session):
    generator = chat.turn("go")
    next(generator)  # start
    next(generator)  # first delta
    generator.close()  # what the WSGI server does when the client disconnects
    partial = session.query(Message).filter_by(role="assistant").one()
    assert partial.status == "partial" and partial.content.strip() == "fake"


def test_refresh_after_interrupted_stream_shows_saved_state(chat, session, user):
    generator = chat.turn("go")
    start = next(generator)
    next(generator)
    generator.close()
    history = ConversationService(session, user.id).messages(start["conversation"]["id"])
    assert [(m.role, m.status) for m in history] == [("user", "complete"), ("assistant", "partial")]


# ------------------------------------------------------------ ownership


def test_cannot_continue_another_users_conversation(session, make_chat, user):
    other = User(username="other", password_hash="x")
    session.add(other)
    session.commit()
    theirs = make_chat(other).reply("secret plans")
    with pytest.raises(NotFoundError):
        make_chat(user).reply("hi", theirs.conversation["id"])
    assert rows(session, theirs.conversation["id"])[-1].content == "fake reply"


def test_unknown_conversation_is_not_found(chat):
    with pytest.raises(NotFoundError):
        chat.reply("hi", 999)


# ------------------------------------------------------------ titles and summaries


def test_llm_title_replaces_auto_title(make_chat, user, llm, session):
    chat = make_chat(user, env={"KYVON_AUTO_TITLE_LLM": "true"})
    llm.script = ["Sure thing!", '"Trip to Lisbon"']
    result = chat.reply("plan my trip to lisbon")
    conversation = ConversationService(session, user.id).get(result.conversation["id"])
    assert conversation.title == "Trip to Lisbon"


def test_user_title_is_never_overwritten(make_chat, user, llm, session):
    chat = make_chat(user, env={"KYVON_AUTO_TITLE_LLM": "true"})
    conversations = ConversationService(session, user.id)
    named = conversations.create("My title")
    llm.script = ["reply", "Generated"]
    chat.reply("hi", named.id)
    assert conversations.get(named.id).title == "My title"


def test_title_failure_does_not_break_the_reply(make_chat, user, llm):
    chat = make_chat(user, env={"KYVON_AUTO_TITLE_LLM": "true"})
    llm.script = ["fine", RuntimeError("title model down")]
    assert chat.reply("hello").message["content"] == "fine"


def test_summary_created_when_history_overflows(make_chat, user, llm, session):
    chat = make_chat(
        user, env={"KYVON_CONTEXT_MAX_MESSAGES": "4", "KYVON_SUMMARY_TRIGGER_MESSAGES": "6"}
    )
    conversation_id = None
    for i in range(6):
        conversation_id = chat.reply(f"message number {i}", conversation_id).conversation["id"]
    conversation = ConversationService(session, user.id).get(conversation_id)
    assert conversation.summary  # the fake model's reply was stored as the summary
    assert conversation.summary_upto_message_id is not None
