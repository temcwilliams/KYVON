from types import SimpleNamespace

from kyvon.llm.groq_client import GroqClient
from kyvon.llm.prompts import SYSTEM_PROMPT, WEB_SYSTEM_PROMPT, build_system_prompt


class FakeGroq:
    def __init__(self, content="  hi  "):
        self.calls = []
        message = SimpleNamespace(content=content)
        self._response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_complete_strips_and_sends_all_options():
    groq = FakeGroq()
    result = GroqClient("k", client=groq).complete(
        [{"role": "user", "content": "x"}], model="m", temperature=0.7, max_tokens=1500
    )
    assert result == "hi"
    assert groq.calls == [
        {
            "model": "m",
            "messages": [{"role": "user", "content": "x"}],
            "temperature": 0.7,
            "max_tokens": 1500,
        }
    ]


def test_optional_params_omitted_when_not_given():
    groq = FakeGroq()
    GroqClient("k", client=groq).complete([], model="m", max_tokens=10)
    assert "temperature" not in groq.calls[0]
    assert groq.calls[0]["max_tokens"] == 10


def test_temperature_zero_is_sent():
    groq = FakeGroq()
    GroqClient("k", client=groq).complete([], model="m", temperature=0)
    assert groq.calls[0]["temperature"] == 0


def test_prompt_builder_fills_placeholders():
    prompt = build_system_prompt("- a memory", "CURRENT LOCATION: X")
    assert "- a memory" in prompt and "CURRENT LOCATION: X" in prompt
    assert "{memory}" not in prompt and "{environment}" not in prompt


def test_memory_with_braces_is_safe():
    assert "{oops}" in build_system_prompt("- {oops}", "env")


def test_prompts_identical_to_prototype(prototype):
    assert SYSTEM_PROMPT == prototype.SYSTEM_PROMPT
    web_call = prototype.web_search("q") and prototype.completions.calls[-1]
    assert web_call["messages"][0]["content"] == WEB_SYSTEM_PROMPT
