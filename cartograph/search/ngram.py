"""
Character n-gram index for fuzzy / typo-tolerant search.

Builds a per-widget n-gram set from searchable fields at index time.
At query time, computes a weighted Jaccard similarity between the query's
n-grams and each widget's field n-grams.

Field weights (higher = more important):
  id / name : 3.0
  tags      : 2.0
  description: 1.0
  source code: 0.3
"""

from __future__ import annotations


_FIELD_WEIGHTS = {
    "id":          3.0,
    "name":        3.0,
    "tags":        2.0,
    "description": 1.0,
    "code":        0.3,
}


def _ngrams(text: str, n: int) -> set[str]:
    """Return the set of character n-grams in text."""
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i: i + n] for i in range(len(text) - n + 1)}


def _field_ngrams(text: str, sizes=(2, 3)) -> set[str]:
    """Union of bigrams and trigrams for a piece of text."""
    grams: set[str] = set()
    for n in sizes:
        grams |= _ngrams(text, n)
    return grams


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class NgramIndex:
    """Builds once, queries many times."""

    def __init__(self):
        # Per-widget, per-field n-gram sets
        self._index: list[dict[str, set[str]]] = []
        self._widgets: list[dict] = []

    def build(self, widgets: list[dict]) -> None:
        self._widgets = widgets
        self._index = []
        for w in widgets:
            tags_text = " ".join(w.get("tags", []))
            entry = {
                "id":          _field_ngrams(w.get("id", "")),
                "name":        _field_ngrams(w.get("name", "")),
                "tags":        _field_ngrams(tags_text),
                "description": _field_ngrams(w.get("description", "")),
                "code":        _field_ngrams(w.get("_code_tokens", "")),
            }
            self._index.append(entry)

    def score(self, query: str) -> list[float]:
        """Return a weighted n-gram score for every widget."""
        query_grams = _field_ngrams(query)
        scores = []
        for entry in self._index:
            weighted = sum(
                _FIELD_WEIGHTS[field] * _jaccard(query_grams, entry[field])
                for field in _FIELD_WEIGHTS
            )
            scores.append(weighted)
        return scores
