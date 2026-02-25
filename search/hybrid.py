"""
Hybrid BM25 + n-gram search backend.

Combines two complementary signals:
  - BM25    : whole-token matching, good for natural-language queries and descriptions
  - N-gram  : character-level fuzzy matching, good for typos, partial IDs, prefix queries

Final score = α * norm(bm25) + β * norm(ngram)

Both score vectors are normalised to [0, 1] before combining so neither
dominates by accident of scale. We weight n-gram slightly higher because
Cartographer queries tend to be short and ID-like.

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


def _normalise(scores: list[float]) -> list[float]:
    """Min-max normalise to [0, 1]. Returns zeros if all scores are equal."""
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [0.0] * len(scores)
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
              language_filter: str | None = None, type_filter: str | None = None,
              top_k: int = 15) -> dict:
        if not self._widgets:
            return {"installed": [], "library": []}

        bm25_raw  = self._bm25.score(query)
        ngram_raw = self._ngram.score(query)

        bm25_norm  = _normalise(bm25_raw)
        ngram_norm = _normalise(ngram_raw)

        query_lower = query.lower()
        scored = []
        for idx, widget in enumerate(self._widgets):
            combined = _ALPHA * bm25_norm[idx] + _BETA * ngram_norm[idx]

            # Hard boost for exact substring in name or id
            if (query_lower in widget.get("name", "").lower() or
                    query_lower in widget.get("id", "").lower()):
                combined += _EXACT_BOOST

            if combined <= 0:
                continue

            if not apply_filters(widget, domain_filter, language_filter, type_filter):
                continue

            scored.append({**widget, "relevance_score": round(combined, 4)})

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return format_results(scored[:top_k])
