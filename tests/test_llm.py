from types import SimpleNamespace

from kyvon.llm.groq_client import GroqClient
from kyvon.llm.prompts import BASE_PROMPT, build_system_prompt


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


def test_prompt_has_separate_context_sections():
    prompt = build_system_prompt(
        profile="likes short answers",
        memory="- a memory",
        summary="we discussed X",
        environment="CURRENT LOCATION: X",
    )
    assert "You are KYVON" in prompt
    for expected in ("likes short answers", "- a memory", "we discussed X", "CURRENT LOCATION: X"):
        assert expected in prompt
    assert prompt.index("- a memory") < prompt.index("we discussed X") < prompt.index("CURRENT LOC")


def test_optional_sections_omitted_when_empty():
    prompt = build_system_prompt(memory="", environment="")
    assert "No relevant saved memories." in prompt
    assert "Summary of earlier" not in prompt and "About the user" not in prompt


def test_memory_with_braces_is_safe():
    assert "{oops}" in build_system_prompt(memory="- {oops}", environment="env")


def test_prompt_treats_tool_output_as_data():
    assert "DATA, not" in BASE_PROMPT and "awaiting confirmation" in BASE_PROMPT


# ------------------------------------------------------------ tool calls, usage, streaming


def _tool_call(index=0, id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=function)


def test_chat_returns_tool_calls_and_usage():
    call = SimpleNamespace(
        id="c1", function=SimpleNamespace(name="get_weather", arguments='{"a":1}')
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        model="m1",
    )
    groq = FakeGroq()
    groq._response = response
    result = GroqClient("k", client=groq).chat([], model="m", tools=[{"type": "function"}])
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("c1", "get_weather", '{"a":1}')
    ]
    assert result.content == "" and result.finish_reason == "tool_calls" and result.model == "m1"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (7, 3)
    assert groq.calls[0]["tools"] == [{"type": "function"}]
    assert groq.calls[0]["tool_choice"] == "auto"


def test_tools_omitted_when_none_given():
    groq = FakeGroq()
    GroqClient("k", client=groq).chat([], model="m")
    assert "tools" not in groq.calls[0] and "tool_choice" not in groq.calls[0]


def _chunk(text=None, tool_calls=None, finish=None, usage=None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    extra = SimpleNamespace(usage=usage) if usage else None
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)], x_groq=extra, usage=None
    )


class StreamingGroq(FakeGroq):
    def __init__(self, chunks):
        super().__init__()
        self.chunks = chunks

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.chunks)


def test_stream_chat_yields_text_then_done_with_usage():
    usage = SimpleNamespace(prompt_tokens=9, completion_tokens=2)
    groq = StreamingGroq([_chunk("Hel"), _chunk("lo"), _chunk(None, finish="stop", usage=usage)])
    events = list(GroqClient("k", client=groq).stream_chat([], model="m"))
    assert [e.type for e in events] == ["text", "text", "done"]
    assert events[-1].response.content == "Hello"
    assert events[-1].response.usage.completion_tokens == 2
    assert groq.calls[0]["stream"] is True


def test_stream_chat_assembles_split_tool_call():
    chunks = [
        _chunk(tool_calls=[_tool_call(0, "c1", "add_task", '{"ti')]),
        _chunk(tool_calls=[_tool_call(0, None, None, 'tle": "x"}')]),
        _chunk(finish="tool_calls"),
    ]
    events = list(GroqClient("k", client=StreamingGroq(chunks)).stream_chat([], model="m"))
    (call,) = events[-1].response.tool_calls
    assert (call.id, call.name, call.arguments) == ("c1", "add_task", '{"title": "x"}')
