"""Append-only error log, in the same text format the prototype writes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path


class ErrorLog:
    def __init__(self, path: Path, *, now: Callable[[], datetime] = datetime.now):
        self.path = Path(path)
        self._now = now

    def log(self, error_type: str, message: str, details: str = "") -> None:
        """Record an error. Logging must never raise, so failures are swallowed."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write("\n")
                f.write("=" * 70 + "\n")
                f.write(f"TIME: {self._now().isoformat()}\n")
                f.write(f"TYPE: {error_type}\n")
                f.write(f"MESSAGE: {message}\n")
                f.write(f"DETAILS:\n{details}\n")
        except Exception:
            pass
