"""System diagnostics for the SYSTEM button."""

from __future__ import annotations

from collections.abc import Callable

from kyvon.llm.base import LLMClient


def run_diagnostics(
    *,
    memory_count: Callable[[], int],
    llm: LLMClient,
    model: str,
    deep: bool,
) -> list[dict]:
    """Return diagnostic rows.

    The prototype always made a live model call. That now only happens when
    ``deep`` is requested, so a plain status check is free.
    """
    results = [{"name": "Python", "status": "ONLINE", "details": "Python runtime operational"}]

    try:
        results.append(
            {"name": "Memory", "status": "ONLINE", "details": f"{memory_count()} memories loaded"}
        )
    except Exception as error:
        results.append({"name": "Memory", "status": "ERROR", "details": str(error)})

    if not deep:
        results.append(
            {
                "name": "Groq AI",
                "status": "CONFIGURED",
                "details": "API key configured (run a deep check to test the connection)",
            }
        )
        return results

    try:
        reply = llm.complete(
            [{"role": "user", "content": "Reply with exactly: ONLINE"}],
            model=model,
            temperature=0,
            max_tokens=10,
        )
        results.append({"name": "Groq AI", "status": "ONLINE", "details": reply})
    except Exception as error:
        results.append({"name": "Groq AI", "status": "ERROR", "details": str(error)})

    return results


def overall_ok(results: list[dict]) -> bool:
    return all(r["status"] != "ERROR" for r in results)
