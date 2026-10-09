"""Rules for what may become a long-term memory, and how the user asks for one.

Three kinds of context stay separate in KYVON:

* conversation context - the messages of one conversation (see ContextBuilder)
* long-term memory     - durable facts the user asked KYVON to keep (this module)
* temporary context    - time, location, weather; rebuilt each turn, never stored
"""

from __future__ import annotations

import hashlib
import re

from kyvon.services.errors import ValidationFailure

CATEGORIES = ("general", "preference", "personal", "project", "routine", "contact")
DEFAULT_CATEGORY = "general"
MIN_IMPORTANCE, MAX_IMPORTANCE, DEFAULT_IMPORTANCE = 1, 5, 3
MIN_LENGTH, MAX_LENGTH = 3, 500

# Things that look like credentials are never stored: memories are shown in prompts
# and returned by the API, so a secret saved here would spread.
_SECRET_PATTERNS = [
    re.compile(r"\b(?:gsk|sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b(?:password|passcode|passwd|pin|api[ _-]?key|secret|token)\b\s*(?:is|:|=)\s*\S+", re.I
    ),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
]

# Order matters: "remember that X" must match before "remember X".
_REMEMBER_PHRASES = ("remember that ", "don't forget that ", "keep in mind that ", "remember ")

_RECALL = re.compile(
    r"^(?:what|which)\s+(?:do|did|can)\s+you\s+(?:remember|know)"
    r"(?:\s+about\s+(?P<topic>.+?))?\s*\??$",
    re.I,
)
_RECALL_ALT = re.compile(
    r"^(?:show|list|tell me)\s+(?:me\s+)?(?:what\s+you\s+remember|(?:all\s+)?(?:your\s+|my\s+)?memories)"
    r"(?:\s+about\s+(?P<topic>.+?))?\s*\??$",
    re.I,
)
_GENERIC_TOPICS = {"me", "myself", "i", "everything", "anything", "us"}


def parse_memory_shortcut(message: str) -> str | None:
    """Return the text to remember if ``message`` starts with a remember-phrase."""
    lower = message.lower()
    for phrase in _REMEMBER_PHRASES:
        if lower.startswith(phrase):
            text = message[len(phrase) :].strip()
            if text:
                return text
    return None


def parse_recall_request(message: str) -> tuple[bool, str | None]:
    """Detect "what do you remember (about X)?". Returns (is_recall, topic)."""
    text = message.strip()
    for pattern in (_RECALL, _RECALL_ALT):
        match = pattern.match(text)
        if match:
            topic = (match.group("topic") or "").strip(" ?.!")
            if topic.lower() in _GENERIC_TOPICS:
                topic = ""
            return True, topic or None
    return False, None


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def validate_memory_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) < MIN_LENGTH:
        raise ValidationFailure("That memory is too short to be useful.")
    if len(cleaned) > MAX_LENGTH:
        raise ValidationFailure(f"Memories are limited to {MAX_LENGTH} characters.")
    if looks_like_secret(cleaned):
        raise ValidationFailure(
            "That looks like a password or key. I don't store secrets in memory."
        )
    return cleaned


def validate_category(category: str | None) -> str:
    value = (category or DEFAULT_CATEGORY).strip().lower()
    if value not in CATEGORIES:
        raise ValidationFailure(f"Category must be one of: {', '.join(CATEGORIES)}.")
    return value


def validate_importance(importance: int | None) -> int:
    value = DEFAULT_IMPORTANCE if importance is None else importance
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationFailure("Importance must be a whole number from 1 to 5.")
    if not MIN_IMPORTANCE <= value <= MAX_IMPORTANCE:
        raise ValidationFailure("Importance must be between 1 and 5.")
    return value
