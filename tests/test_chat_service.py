import pytest

from kyvon.services.chat_service import ChatInputError, ChatService
from tests.fakes import FakeLLM


@pytest.fixture
def llm():
    return FakeLLM()


class ListMemory:
    """Minimal in-memory MemoryPort (same 20-item prompt rule as the real service)."""

    def __init__(self):
        self.items = []

    def add(self, text):
        self.items.append({"memory": text})

    def all(self):
        return list(self.items)

    def prompt_text(self):
        if not self.items:
            return "No saved memories."
        return "\n".join(f"- {m['memory']}" for m in self.items[-20:])


@pytest.fixture
def memory():
    return ListMemory()


@pytest.fixture
def chat(llm, memory):
    return ChatService(llm, memory, model="main-model", web_model="web-model")


def test_plain_chat_uses_main_model_and_prompt(chat, llm):
    assert chat.reply("hello") == {"response": "fake reply"}
    (call,) = llm.calls
    assert call["model"] == "main-model"
    assert call["temperature"] == 0.7 and call["max_tokens"] == 1500
    system, user = call["messages"]
    assert "You are KYVON" in system["content"]
    assert user == {"role": "user", "content": "hello"}


def test_chat_is_stateless(chat, llm):
    chat.reply("one")
    chat.reply("two")
    assert all([m["role"] for m in c["messages"]] == ["system", "user"] for c in llm.calls)


def test_environment_and_memory_in_prompt(chat, llm):
    chat.reply("remember I like tea")
    chat.reply("hi", "CURRENT LOCATION: Testville")
    system = llm.calls[0]["messages"][0]["content"]
    assert "- I like tea" in system and "CURRENT LOCATION: Testville" in system


def test_defaults_in_prompt(chat, llm):
    chat.reply("hi")
    system = llm.calls[0]["messages"][0]["content"]
    assert "No location information available." in system
    assert "No saved memories." in system


def test_memory_shortcut_saves_without_model(chat, llm, memory):
    assert chat.reply("remember my dog is Rex") == {
        "response": "Understood. I have saved that to my memory.",
        "memory_saved": True,
    }
    assert llm.calls == []
    assert [m["memory"] for m in memory.all()] == ["my dog is Rex"]


def test_remember_that_quirk_preserved(chat, memory):
    chat.reply("remember that I am tall")
    assert memory.all()[0]["memory"] == "that I am tall"


@pytest.mark.parametrize("phrase", ["don't forget that ", "keep in mind that "])
def test_other_shortcuts(chat, memory, phrase):
    assert chat.reply(phrase + "milk")["memory_saved"] is True
    assert memory.all()[-1]["memory"] == "milk"


def test_bare_remember_goes_to_model(chat, llm):
    assert chat.reply("remember") == {"response": "fake reply"}
    assert len(llm.calls) == 1


def test_web_uses_web_model(chat, llm):
    assert chat.reply("web latest python") == {"response": "fake reply", "web": True}
    (call,) = llm.calls
    assert call["model"] == "web-model"
    assert call["temperature"] is None and call["max_tokens"] == 1500
    assert call["messages"][1]["content"] == "latest python"


def test_bare_web_goes_to_main_model(chat, llm):
    chat.reply("web")
    assert llm.calls[0]["model"] == "main-model"


def test_web_prefix_case_insensitive(chat, llm):
    assert chat.reply("WEB rain")["web"] is True


def test_blank_message_rejected(chat):
    with pytest.raises(ChatInputError):
        chat.reply("   ")


def test_message_is_stripped(chat, llm):
    chat.reply("  hi  ")
    assert llm.calls[0]["messages"][1]["content"] == "hi"


def test_llm_error_propagates(chat, llm):
    llm.error = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        chat.reply("hi")
