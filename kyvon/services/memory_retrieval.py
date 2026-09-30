"""Choosing which memories are relevant to what the user just said.

``MemoryRetriever`` is the seam: today's implementation is lexical (BM25-style term
weighting with light stemming, plus importance and recency). A semantic implementation
could be added behind the same interface without touching callers; none is bundled
because Groq offers no embeddings endpoint and a local embedding model would add heavy
dependencies for a store of a few hundred short facts.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kyvon.models import Memory

STOPWORDS = frozenset(
    """a an and are as at be but by can could did do does for from had has have how i if in
    into is it its me my of on or our so that the their them then there these they this to
    was we were what when where which who why will with would you your about any some tell
    know remember please just like get got""".split()
)
_WORD = re.compile(r"[a-z0-9']+")

UNSEEN_WEIGHT = 0.3  # weight of query words no memory contains
MIN_RELEVANCE = 0.2  # below this a memory is not relevant enough to inject
CORE_IMPORTANCE = 5
MAX_CORE = 3


def stem(word: str) -> str:
    """A small suffix stripper: running/runs/run -> run, likes/liked/like -> lik."""
    word = word.replace("'s", "").strip("'")
    if len(word) > 4 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 3 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
        word = word[:-1]  # running -> runn -> run
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]  # make/making/makes agree
    return word


def tokens(text: str) -> list[str]:
    words = (w for w in _WORD.findall((text or "").lower()) if w not in STOPWORDS)
    return [s for w in words if len(s := stem(w)) > 1 and s not in STOPWORDS]


@dataclass(frozen=True)
class Scored:
    memory: Memory
    score: float
    core: bool = False


class MemoryRetriever(Protocol):
    def rank(
        self, query: str, memories: list[Memory], k: int, *, now: datetime
    ) -> list[Scored]: ...


class LexicalRetriever:
    """Term-overlap ranking over the user's own memories."""

    k1 = 1.4
    b = 0.6

    def rank(self, query: str, memories: list[Memory], k: int, *, now: datetime) -> list[Scored]:
        docs = [(m, tokens(m.content)) for m in memories]
        core = [
            Scored(m, float(CORE_IMPORTANCE), core=True)
            for m in sorted(memories, key=lambda m: m.created_at, reverse=True)
            if m.importance >= CORE_IMPORTANCE
        ][:MAX_CORE]
        core_ids = {s.memory.id for s in core}

        query_terms = set(tokens(query))
        if not query_terms or not docs:
            return core[:k]

        n = len(docs)
        avg_len = (sum(len(t) for _, t in docs) / n) or 1.0
        doc_freq = Counter(term for _, t in docs for term in set(t))

        def idf(term: str) -> float:
            return math.log(1 + n / (doc_freq.get(term, 0) + 0.5))

        # Relevance is the share of the query's weight that the memory covers, so it
        # means the same thing for short and long queries and for small and large stores.
        # Words that appear in none of the user's memories count for less: chatty
        # filler should not drown out the one word that matters.
        total_weight = sum(idf(t) * (1.0 if t in doc_freq else UNSEEN_WEIGHT) for t in query_terms)

        scored: list[Scored] = []
        for memory, terms in docs:
            if memory.id in core_ids or not terms:
                continue
            freq = Counter(terms)
            matched = 0.0
            for term in query_terms:
                if term not in freq:
                    continue
                tf = freq[term]
                saturation = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * len(terms) / avg_len)
                )
                matched += idf(term) * min(saturation, 1.0)
            relevance = matched / total_weight if total_weight else 0.0
            if relevance < MIN_RELEVANCE:
                continue
            importance_boost = 1 + 0.1 * (memory.importance - 3)
            age_days = max((now - memory.created_at).total_seconds() / 86400, 0)
            recency_boost = 1 + 0.15 * math.exp(-age_days / 60)
            scored.append(Scored(memory, relevance * importance_boost * recency_boost))

        scored.sort(key=lambda s: (-s.score, -s.memory.id))
        return (core + scored)[:k]
