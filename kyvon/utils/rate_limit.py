"""Tiny in-memory failure throttle for the login endpoint (per process)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class FailureThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 900,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_failures = max_failures
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = self._clock() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key)
            self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class RateLimiter:
    """Per-key sliding-window limiter (in memory, per process).

    KYVON runs one worker, so this is accurate for it; with several workers each would
    enforce the limit separately (a documented limitation).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, seconds_until_allowed_again)."""
        now = self._clock()
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if t > now - window]
            if len(recent) >= limit:
                self._hits[key] = recent
                return False, max(1, int(recent[0] + window - now) + 1)
            recent.append(now)
            self._hits[key] = recent
            if len(self._hits) > 10_000:  # bound memory: drop idle keys
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
                    del self._hits[stale]
            return True, 0
