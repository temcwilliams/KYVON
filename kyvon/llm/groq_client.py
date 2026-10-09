"""Groq implementation of the LLM interface."""

from __future__ import annotations

from collections.abc import Iterator

from groq import Groq

from kyvon.llm.base import LLMResponse, StreamEvent, ToolCall, Usage


def _usage(obj) -> Usage | None:
    if obj is None:
        return None
    return Usage(
        prompt_tokens=getattr(obj, "prompt_tokens", None),
        completion_tokens=getattr(obj, "completion_tokens", None),
    )


class GroqClient:
    def __init__(self, api_key: str, *, client: Groq | None = None, timeout: float = 60.0):
        self._client = client or Groq(api_key=api_key, timeout=timeout)

    @staticmethod
    def _kwargs(messages, model, tools, temperature, max_tokens) -> dict:
        # Only send optional parameters that were asked for, exactly as the
        # prototype did (e.g. web search sends no temperature).
        kwargs: dict = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        response = self._client.chat.completions.create(
            **self._kwargs(messages, model, None, temperature, max_tokens)
        )
        return (response.choices[0].message.content or "").strip()

    def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        response = self._client.chat.completions.create(
            **self._kwargs(messages, model, tools, temperature, max_tokens)
        )
        choice = response.choices[0]
        message = choice.message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (getattr(message, "tool_calls", None) or [])
        ]
        return LLMResponse(
            content=(message.content or "").strip(),
            tool_calls=calls,
            usage=_usage(getattr(response, "usage", None)),
            model=getattr(response, "model", model) or model,
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def stream_chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        stream = self._client.chat.completions.create(
            stream=True, **self._kwargs(messages, model, tools, temperature, max_tokens)
        )
        text: list[str] = []
        partial: dict[int, dict] = {}
        usage = None
        finish = None
        for chunk in stream:
            # Groq reports usage on the final chunk under ``x_groq``.
            extra = getattr(chunk, "x_groq", None)
            if extra is not None and getattr(extra, "usage", None) is not None:
                usage = _usage(extra.usage)
            elif getattr(chunk, "usage", None) is not None:
                usage = _usage(chunk.usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, "content", None):
                text.append(delta.content)
                yield StreamEvent("text", text=delta.content)
            for call in getattr(delta, "tool_calls", None) or []:
                slot = partial.setdefault(call.index or 0, {"id": "", "name": "", "arguments": ""})
                if call.id:
                    slot["id"] = call.id
                if call.function is not None:
                    if call.function.name:
                        slot["name"] += call.function.name
                    if call.function.arguments:
                        slot["arguments"] += call.function.arguments
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason

        calls = [
            ToolCall(id=s["id"] or f"call_{i}", name=s["name"], arguments=s["arguments"] or "{}")
            for i, s in sorted(partial.items())
        ]
        yield StreamEvent(
            "done",
            response=LLMResponse(
                content="".join(text).strip(),
                tool_calls=calls,
                usage=usage,
                model=model,
                finish_reason=finish,
            ),
        )
