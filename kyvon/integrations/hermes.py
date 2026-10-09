"""Hermes as an optional agent backend.

What Hermes is here: a language-model endpoint that speaks the OpenAI chat-completions
protocol (for example a Hermes model served by vLLM/Ollama/LM Studio, or a compatible gateway).
KYVON stays the assistant the user talks to. Hermes never gets tools of its own through KYVON:
when it asks for a tool, the request goes through KYVON's executor with the agent's allow-list,
argument validation, confirmation rules, timeouts and audit log, exactly like any other agent.

The boundary KYVON *cannot* enforce: if the configured endpoint is itself an autonomous agent
with its own shell or file tools, those are outside KYVON's control. Point KYVON at a model
endpoint, or a sandboxed agent, never at something with access to the production VM.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from kyvon.config import Settings
from kyvon.llm.openai_compat import OpenAICompatClient

_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


class HermesConfigError(ValueError):
    pass


def validate_url(url: str, *, allow_remote: bool) -> str:
    """Only http(s) URLs without embedded credentials; private hosts unless allowed."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HermesConfigError("KYVON_HERMES_URL must be an http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise HermesConfigError(
            "KYVON_HERMES_URL must not contain credentials; use KYVON_HERMES_API_KEY."
        )
    host = parsed.hostname.lower()
    if allow_remote:
        return url
    if host == "localhost" or host.endswith(_PRIVATE_SUFFIXES):
        return url
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (address.is_loopback or address.is_private or address.is_link_local):
        return url
    raise HermesConfigError(
        "KYVON_HERMES_URL points outside your private network. If that is intended, set "
        "KYVON_HERMES_ALLOW_REMOTE=true."
    )


@dataclass
class HermesBackend:
    llm: OpenAICompatClient
    model: str
    base_url: str

    def health(self) -> dict:
        return {"configured": True, "model": self.model, **self.llm.health()}


def build_hermes(settings: Settings, http) -> HermesBackend | None:
    """Create the backend when configured, else None (Hermes is optional)."""
    if not settings.hermes_url:
        return None
    url = validate_url(settings.hermes_url, allow_remote=settings.hermes_allow_remote)
    return HermesBackend(
        llm=OpenAICompatClient(
            url,
            api_key=settings.hermes_api_key,
            http=http,
            timeout=settings.hermes_timeout_seconds,
        ),
        model=settings.hermes_model,
        base_url=url,
    )
