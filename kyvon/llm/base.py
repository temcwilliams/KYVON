"""Provider-agnostic interface the rest of KYVON depends on."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model. ``arguments`` is the raw JSON string."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    model: str = ""
    finish_reason: str | None = None


@dataclass
class StreamEvent:
    """``text`` events carry a delta; the single final ``done`` event carries the response."""

    type: str  # "text" | "done"
    text: str = ""
    response: LLMResponse | None = None


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send chat ``messages`` and return the reply text, stripped."""
        ...

    def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Like ``complete`` but returns tool calls and usage too."""
        ...

    def stream_chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        """Yield ``text`` deltas, then one ``done`` event with the assembled response."""
        ...
