"""
Hybrid BM25 + n-gram search backend.

Combines two complementary signals:
  - BM25    : whole-token matching, good for natural-language queries and descriptions
  - N-gram  : character-level fuzzy matching, good for typos, partial IDs, prefix queries

Final score = α * norm(bm25) + β * norm(ngram)

Both score vectors are normalised to [0, 1] before combining so neither
dominates by accident of scale. We weight n-gram slightly higher because
Cartograph queries tend to be short and ID-like.

Additionally, exact substring matches in name/id get a hard boost so that
"auth" always surfaces "Auth Middleware" near the top regardless of corpus
statistics.
"""

from __future__ import annotations

from .base import SearchBackend
from .bm25 import BM25Backend
from .filters import apply_filters, format_results
from .ngram import NgramIndex

# Mix weights — must sum to 1.0
_ALPHA = 0.40   # BM25 contribution
_BETA  = 0.60   # N-gram contribution

# Score boost for exact substring match in name or id (added after normalisation)
_EXACT_BOOST = 0.30

# Minimum combined score to appear in results — filters out weak/tangential matches
_MIN_SCORE = 0.10


def _normalise(scores: list[float]) -> list[float]:
    """Min-max normalise to [0, 1].

    When all scores are equal (including the single-widget case), return
    1.0 for any non-zero score so that the signal isn't silently discarded.
    """
    lo, hi = min(scores), max(scores)
    if hi == lo:
        # Preserve the signal: non-zero scores → 1.0, true zeros stay 0.0
        return [1.0 if s > 0 else 0.0 for s in scores]
    span = hi - lo
    return [(s - lo) / span for s in scores]


class HybridBackend(SearchBackend):
    def __init__(self):
        self._bm25 = BM25Backend()
        self._ngram = NgramIndex()
        self._widgets: list[dict] = []

    def build(self, widgets: list[dict]) -> None:
        self._widgets = widgets
        self._bm25.build(widgets)
        self._ngram.build(widgets)

    def query(self, query: str, domain_filter: str | None = None,
              language_filter: str | None = None, top_k: int = 10) -> dict:
        if not self._widgets:
            return {"results": []}

        bm25_raw  = self._bm25.score(query)
        ngram_raw = self._ngram.score(query)

        bm25_norm  = _normalise(bm25_raw)
        ngram_norm = _normalise(ngram_raw)

        query_lower = query.lower()
        scored = []
        for idx, widget in enumerate(self._widgets):
            combined = _ALPHA * bm25_norm[idx] + _BETA * ngram_norm[idx]

            # Hard boost for exact substring in name or id (per query term)
            name_lower = widget.get("name", "").lower()
            id_lower = widget.get("id", "").lower()
            for term in query_lower.split():
                if term in name_lower or term in id_lower:
                    combined += _EXACT_BOOST
                    break

            if combined < _MIN_SCORE:
                continue

            if not apply_filters(widget, domain_filter, language_filter):
                continue

            scored.append({**widget, "relevance_score": round(combined, 4)})

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return format_results(scored[:top_k])
