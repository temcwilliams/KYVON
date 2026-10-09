"""Tiny in-memory failure throttle for the login endpoint (per process)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta


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

    def count(self, key: str) -> int:
        with self._lock:
            return len(self._recent(key))

    def blocked(self, key: str) -> bool:
        return self.count(key) >= self.max_failures

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


class DbRateLimiter:
    """Sliding-window limiter stored in the database, so every server process shares one count.

    Same ``hit`` interface as RateLimiter. A hit costs one small INSERT, so it is used for the
    security-sensitive anonymous endpoints, not for every authenticated API call.
    """

    def __init__(self, session_factory, *, clock: Callable[[], datetime] | None = None):
        from kyvon.db import utcnow

        self._sessions = session_factory
        self._now = clock or utcnow
        self._calls = 0

    def hit(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        from sqlalchemy import func, select

        from kyvon.models import RateHit

        now = self._now()
        since = now - timedelta(seconds=window)
        key = key[:200]
        with self._sessions() as session:
            rows = session.execute(
                select(func.count(), func.min(RateHit.at)).where(
                    RateHit.key == key, RateHit.at > since
                )
            ).one()
            count, oldest = rows
            if count >= limit:
                wait = int((oldest + timedelta(seconds=window) - now).total_seconds()) + 1
                return False, max(1, wait)
            session.add(RateHit(key=key, at=now))
            session.commit()
            self._calls += 1
            if self._calls % 200 == 0:
                self._prune(session, now - timedelta(hours=2))
        return True, 0

    @staticmethod
    def _prune(session, before) -> None:
        from sqlalchemy import delete

        from kyvon.models import RateHit

        session.execute(delete(RateHit).where(RateHit.at < before))
        session.commit()


class DbFailureThrottle:
    """The login failure throttle (see FailureThrottle), shared across processes."""

    def __init__(
        self,
        session_factory,
        max_failures: int = 5,
        window_seconds: int = 900,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        from kyvon.db import utcnow

        self._sessions = session_factory
        self.max_failures = max_failures
        self.window = window_seconds
        self._now = clock or utcnow

    def count(self, key: str) -> int:
        from sqlalchemy import func, select

        from kyvon.models import RateHit

        since = self._now() - timedelta(seconds=self.window)
        with self._sessions() as session:
            return int(
                session.scalar(
                    select(func.count()).where(
                        RateHit.key == f"fail:{key}"[:200], RateHit.at > since
                    )
                )
                or 0
            )

    def blocked(self, key: str) -> bool:
        return self.count(key) >= self.max_failures

    def record_failure(self, key: str) -> None:
        from kyvon.models import RateHit

        with self._sessions() as session:
            session.add(RateHit(key=f"fail:{key}"[:200], at=self._now()))
            session.commit()

    def reset(self, key: str) -> None:
        from sqlalchemy import delete

        from kyvon.models import RateHit

        with self._sessions() as session:
            session.execute(delete(RateHit).where(RateHit.key == f"fail:{key}"[:200]))
            session.commit()
