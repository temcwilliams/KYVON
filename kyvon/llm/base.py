"""Provider-agnostic interface the rest of KYVON depends on."""

from __future__ import annotations

from typing import Protocol


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
