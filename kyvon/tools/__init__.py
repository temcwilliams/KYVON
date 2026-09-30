"""KYVON's tool system."""

from __future__ import annotations

from kyvon.tools.registry import ToolRegistry


def build_registry() -> ToolRegistry:
    """A registry containing every built-in tool."""
    from kyvon.tools.builtin import (
        agent_tools,
        calendar_tools,
        conversation_tools,
        environment_tools,
        logseq_tools,
        memory_tools,
        task_tools,
        web_tools,
    )

    registry = ToolRegistry()
    for module in (
        memory_tools,
        web_tools,
        environment_tools,
        conversation_tools,
        task_tools,
        calendar_tools,
        agent_tools,
        logseq_tools,
    ):
        module.register(registry)
    return registry
