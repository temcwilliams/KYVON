"""Best-effort removal of secrets from text that is logged or stored for audit."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    (re.compile(r"\b(?:gsk|sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"), "[redacted-key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[redacted-key]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "[redacted-key]"),
    (re.compile(r"\bkyv_[A-Za-z0-9_-]{20,}"), "[redacted-token]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I), "Bearer [redacted]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
        "[redacted-private-key]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|passcode|secret|token|api[_ -]?key|client_secret)(\"?\s*[:=]\s*\"?)[^\s\"',}]+"
        ),
        r"\1\2[redacted]",
    ),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_data(value: Any) -> Any:
    """Redact every string inside nested dicts/lists (returns a copy)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_data(v) for v in value]
    return value
