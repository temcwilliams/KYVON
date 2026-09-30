"""The registry of tools KYVON may use."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from kyvon.tools.base import RiskLevel, Tool, ToolArgs


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        if tool.retries and tool.risk != RiskLevel.READ:
            raise ValueError(f"{tool.name}: only READ tools may be retried automatically")
        self._tools[tool.name] = tool
        return tool

    def tool(
        self,
        name: str,
        description: str,
        args: type[ToolArgs],
        *,
        risk: RiskLevel = RiskLevel.READ,
        **options: Any,
    ) -> Callable:
        """Decorator form: ``@registry.tool("name", "what it does", ArgsModel, risk=...)``."""

        def decorator(handler: Callable) -> Callable:
            self.register(Tool(name, description, args, handler, risk=risk, **options))
            return handler

        return decorator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def available(self, services: Any, allowed: Iterable[str] | None = None) -> list[Tool]:
        """Enabled tools, optionally restricted to an allow-list (agents use this)."""
        allow = set(allowed) if allowed is not None else None
        return [
            t
            for t in (self._tools[n] for n in sorted(self._tools))
            if (allow is None or t.name in allow) and t.is_enabled(services)
        ]

    def specs(self, services: Any, allowed: Iterable[str] | None = None) -> list[dict]:
        return [t.spec(services) for t in self.available(services, allowed)]
