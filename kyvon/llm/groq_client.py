"""Groq implementation of the LLM interface."""

from __future__ import annotations

from groq import Groq


class GroqClient:
    def __init__(self, api_key: str, *, client: Groq | None = None):
        self._client = client or Groq(api_key=api_key)

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        # Only send optional parameters that were asked for, exactly as the
        # prototype did (e.g. web search sends no temperature).
        kwargs: dict = {"model": model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
