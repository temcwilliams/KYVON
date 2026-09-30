"""A client for any OpenAI-compatible chat-completions endpoint (used for Hermes).

HTTP is injected (``request(method, url, ...)``), so tests never touch the network. The
API key, when set, is only ever sent in the Authorization header and never logged.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from kyvon.llm.base import LLMResponse, StreamEvent, ToolCall, Usage


class LLMError(RuntimeError):
    """The endpoint failed, was unreachable, or returned something unusable."""


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        http: Any,
        timeout: float = 90.0,
    ):
        base = base_url.rstrip("/")
        self._endpoint = base + (
            "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
        )
        self._models_endpoint = base + ("/models" if base.endswith("/v1") else "/v1/models")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._http = http
        self._timeout = timeout

    # ------------------------------------------------------------------ transport

    def _post(self, payload: dict) -> dict:
        try:
            response = self._http.request(
                "POST",
                self._endpoint,
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except Exception as error:  # connection refused, timeout, DNS...
            raise LLMError(f"Could not reach the endpoint ({type(error).__name__}).") from error
        if response.status_code >= 400:
            raise LLMError(f"The endpoint returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as error:
            raise LLMError("The endpoint returned something that is not JSON.") from error

    def health(self) -> dict:
        """Cheap reachability check (lists models). Returns {"reachable": bool, ...}."""
        try:
            response = self._http.request(
                "GET",
                self._models_endpoint,
                headers=self._headers,
                timeout=5,
                allow_redirects=False,
            )
        except Exception as error:
            return {"reachable": False, "error": type(error).__name__}
        if response.status_code >= 400:
            return {"reachable": False, "error": f"HTTP {response.status_code}"}
        try:
            models = [m.get("id") for m in response.json().get("data", []) if isinstance(m, dict)]
        except ValueError:
            models = []
        return {"reachable": True, "models": models[:20]}

    # ------------------------------------------------------------------ LLMClient

    @staticmethod
    def _payload(messages, model, tools, temperature, max_tokens) -> dict:
        payload: dict = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body = self._post(self._payload(messages, model, tools, temperature, max_tokens))
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError("The endpoint's reply had no message.") from error

        calls = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            function = raw.get("function") or {}
            arguments = function.get("arguments", "{}")
            if not isinstance(arguments, str):  # some servers return an object, not a string
                arguments = json.dumps(arguments)
            calls.append(
                ToolCall(
                    id=raw.get("id") or f"call_{index}",
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )
        usage = body.get("usage") or {}
        return LLMResponse(
            content=(message.get("content") or "").strip(),
            tool_calls=calls,
            usage=Usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
            if usage
            else None,
            model=body.get("model") or model,
            finish_reason=choice.get("finish_reason"),
        )

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return self.chat(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        ).content

    def stream_chat(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        """Not token-streamed: one request, then the whole text as a single event.

        Agents (the only user of this client) call ``chat``; this exists to satisfy the
        interface without pretending to stream.
        """
        response = self.chat(
            messages, model=model, tools=tools, temperature=temperature, max_tokens=max_tokens
        )
        if response.content:
            yield StreamEvent("text", text=response.content)
        yield StreamEvent("done", response=response)
