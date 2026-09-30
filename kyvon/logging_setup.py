"""Structured logging with request ids and secret redaction.

* Production logs are one JSON object per line (easy for journald and log tools);
  development logs are readable text.
* Every record carries the request id (and user id when known), so one request can be followed
  across the access log, tool runs and errors.
* Everything passes through ``redact`` so keys, bearer tokens and passwords never reach a log.
* Request bodies and query strings are never logged.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from kyvon.utils.redact import redact

request_id_var: ContextVar[str | None] = ContextVar("kyvon_request_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("kyvon_user_id", default=None)
_MARK = "_kyvon_handler"
_STANDARD = set(logging.LogRecord("x", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if getattr(record, "user_id", None) is not None:
            entry["user_id"] = record.user_id
        for key, value in record.__dict__.items():
            if (
                key not in _STANDARD
                and key not in ("request_id", "user_id")
                and not key.startswith("_")
            ):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None)
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if rid:
            base += f" [{rid}]"
        if record.exc_info:
            base += "\n" + redact(self.formatException(record.exc_info))
        return base


def configure_logging(level: str = "INFO", *, json_format: bool = False) -> None:
    """Idempotent: calling it again replaces KYVON's handler rather than adding another."""
    root = logging.getLogger("kyvon")
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _MARK, True)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if json_format else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
