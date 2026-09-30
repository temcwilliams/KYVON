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


class FakeHTTPResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": "application/json"}
        self.text = "" if body is None else "json"

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeGoogle:
    """An in-memory stand-in for Google's OAuth and Calendar endpoints."""

    def __init__(self):
        self.calls: list[dict] = []
        self.events: dict[str, dict] = {}
        self.valid_refresh = {"refresh-1"}
        self.valid_access: set[str] = set()
        self.token_counter = 0
        self.code = "good-code"
        self.issue_refresh_token = True
        self.token_status = 200
        self.last_verifier: str | None = None
        self.email = "owner@example.com"
        self._next_id = 1

    # -- request router
    def request(self, method, url, headers=None, params=None, data=None, json=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "data": data,
                "json": json,
            }
        )
        if url == "https://oauth2.googleapis.com/token":
            return self._token(data or {})
        if url == "https://oauth2.googleapis.com/revoke":
            return FakeHTTPResponse(200, {})
        if not url.startswith("https://www.googleapis.com/calendar/v3"):
            raise AssertionError(f"unexpected URL {url}")
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_access:
            return FakeHTTPResponse(401, {"error": {"message": "Invalid Credentials"}})
        path = url.removeprefix("https://www.googleapis.com/calendar/v3")
        return self._api(method, path, params or {}, json)

    def _token(self, data):
        if self.token_status != 200:
            return FakeHTTPResponse(self.token_status, {"error": "server_error"})
        assert data.get("client_id") == "test-client-id"
        assert data.get("client_secret") == "test-client-secret"
        if data.get("grant_type") == "authorization_code":
            self.last_verifier = data.get("code_verifier")
            if data.get("code") != self.code:
                return FakeHTTPResponse(400, {"error": "invalid_grant"})
            refresh = "refresh-1" if self.issue_refresh_token else None
        elif data.get("grant_type") == "refresh_token":
            if data.get("refresh_token") not in self.valid_refresh:
                return FakeHTTPResponse(
                    400, {"error": "invalid_grant", "error_description": "Token revoked"}
                )
            refresh = None
        else:
            return FakeHTTPResponse(400, {"error": "unsupported_grant_type"})
        self.token_counter += 1
        access = f"access-{self.token_counter}"
        self.valid_access.add(access)
        body = {"access_token": access, "expires_in": 3600, "scope": "calendar.events"}
        if refresh:
            body["refresh_token"] = refresh
        return FakeHTTPResponse(200, body)

    # -- calendar API
    def _api(self, method, path, params, body):
        if path == "/users/me/calendarList":
            return FakeHTTPResponse(
                200,
                {
                    "items": [
                        {
                            "id": self.email,
                            "summary": "Owner",
                            "primary": True,
                            "timeZone": "America/Chicago",
                            "accessRole": "owner",
                        },
                        {
                            "id": "work@group.calendar.google.com",
                            "summary": "Work",
                            "accessRole": "writer",
                        },
                    ]
                },
            )
        parts = path.strip("/").split("/")  # calendars/<id>/events[/<eid>]
        if parts[0] != "calendars" or parts[2] != "events":
            return FakeHTTPResponse(404, {"error": {"message": "not found"}})
        if len(parts) == 3 and method == "GET":
            return FakeHTTPResponse(200, {"items": self._filter(params)})
        if len(parts) == 3 and method == "POST":
            event = dict(body)
            event["id"] = f"evt{self._next_id}"
            self._next_id += 1
            event["status"] = "confirmed"
            self.events[event["id"]] = event
            return FakeHTTPResponse(200, event)
        event = self.events.get(parts[3])
        if event is None:
            return FakeHTTPResponse(404, {"error": {"message": "Not Found"}})
        if method == "GET":
            return FakeHTTPResponse(200, event)
        if method == "PATCH":
            event.update(body)
            return FakeHTTPResponse(200, event)
        if method == "DELETE":
            del self.events[parts[3]]
            return FakeHTTPResponse(204, None)
        return FakeHTTPResponse(405, {})

    def _filter(self, params):
        from datetime import datetime

        def instant(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        def start_of(event):
            raw = event["start"].get("dateTime") or event["start"]["date"] + "T00:00:00+00:00"
            return instant(raw)

        low, high = instant(params["timeMin"]), instant(params["timeMax"])
        query = (params.get("q") or "").lower()
        found = [
            e
            for e in self.events.values()
            if low <= start_of(e) < high
            and (not query or query in (e.get("summary", "") + e.get("description", "")).lower())
        ]
        return sorted(found, key=start_of)[: int(params.get("maxResults", 25))]

    def add_event(self, summary, start, end, **extra):
        event = {"id": f"evt{self._next_id}", "summary": summary, "status": "confirmed", **extra}
        self._next_id += 1
        event["start"], event["end"] = start, end
        self.events[event["id"]] = event
        return event


class FakeHermesHTTP:
    """A stand-in for an OpenAI-compatible endpoint. Replies come from ``script``."""

    def __init__(self):
        self.requests: list[dict] = []
        self.script: list = []  # dict bodies, Exceptions, or ints (HTTP error status)
        self.models = ["hermes-3"]

    def request(self, method, url, headers=None, json=None, timeout=None, **kwargs):
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        if url.endswith("/models"):
            return FakeHTTPResponse(200, {"data": [{"id": m} for m in self.models]})
        item = self.script.pop(0) if self.script else self.message("A reply from Hermes.")
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return FakeHTTPResponse(item, {"error": "nope"})
        return FakeHTTPResponse(200, item)

    @staticmethod
    def message(content="", tool_calls=None, usage=(11, 7)):
        message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "model": "hermes-3",
            "choices": [
                {"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}
            ],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        }

    @staticmethod
    def tool_call(id, name, arguments):
        import json as _json

        return {
            "id": id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments
                if isinstance(arguments, (str, dict))
                else _json.dumps(arguments),
            },
        }


class FakeSTT:
    """Speech-to-text stand-in: records what it was given."""

    def __init__(self, text="hello from the recording"):
        self.text = text
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def transcribe(self, audio, filename, *, language=None):
        self.calls.append({"size": len(audio), "filename": filename, "language": language})
        if self.error:
            raise self.error
        return self.text
