"""Test doubles shared across test modules."""

from __future__ import annotations


class FakeLLM:
    """Implements kyvon.llm.base.LLMClient; records calls, never touches the network."""

    def __init__(self, reply: str = "fake reply"):
        self.reply = reply
        self.error: Exception | None = None
        self.calls: list[dict] = []

    def complete(self, messages, *, model, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.error:
            raise self.error
        return self.reply
