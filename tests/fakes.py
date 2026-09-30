"""Test doubles shared across test modules."""

from __future__ import annotations

import re

from kyvon.llm.base import LLMResponse, StreamEvent, Usage


class FakeLLM:
    """Implements kyvon.llm.base.LLMClient; records calls, never touches the network.

    ``script`` is a queue consumed by ``chat`` / ``stream_chat`` / ``complete``. Items may be
    a string (reply text), an ``LLMResponse`` or an ``Exception`` (raised). When the queue is
    empty the default ``reply`` is used.
    """

    def __init__(self, reply: str = "fake reply"):
        self.reply = reply
        self.error: Exception | None = None
        self.calls: list[dict] = []
        self.script: list = []
        self.stream_error_after: int | None = None  # raise after N text chunks

    # -- helpers
    def _record(self, kind, messages, model, tools, temperature, max_tokens):
        self.calls.append(
            {
                "kind": kind,
                "messages": messages,
                "model": model,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.error:
            raise self.error

    def _next(self, model) -> LLMResponse:
        item = self.script.pop(0) if self.script else self.reply
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            if not item.model:
                item.model = model
            if item.usage is None:
                item.usage = Usage(10, 5)
            return item
        return LLMResponse(content=item, usage=Usage(10, 5), model=model, finish_reason="stop")

    # -- LLMClient
    def complete(self, messages, *, model, temperature=None, max_tokens=None):
        self._record("complete", messages, model, None, temperature, max_tokens)
        return self._next(model).content

    def chat(self, messages, *, model, tools=None, temperature=None, max_tokens=None):
        self._record("chat", messages, model, tools, temperature, max_tokens)
        return self._next(model)

    def stream_chat(self, messages, *, model, tools=None, temperature=None, max_tokens=None):
        self._record("stream", messages, model, tools, temperature, max_tokens)
        response = self._next(model)
        for count, piece in enumerate(re.findall(r"\S+\s*", response.content)):
            if self.stream_error_after is not None and count >= self.stream_error_after:
                raise RuntimeError("stream broke")
            yield StreamEvent("text", text=piece)
        yield StreamEvent("done", response=response)
