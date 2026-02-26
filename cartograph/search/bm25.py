"""
BM25 backend — built once at index time, not per query.

Uses field-weighted corpus construction so name/tag hits matter more
than source code hits. Synonym expansion is loaded from synonyms.json.
"""

from __future__ import annotations

import json
import os
import re

from rank_bm25 import BM25Okapi

from .base import SearchBackend

_SYNONYMS_PATH = os.path.join(os.path.dirname(__file__), "synonyms.json")

try:
    with open(_SYNONYMS_PATH) as f:
        _SYNONYMS: dict[str, list[str]] = json.load(f)
except Exception:
    _SYNONYMS = {}

# How many times to repeat each field's tokens in the corpus document.
# Repetition gives BM25 a crude field-weight approximation.
_FIELD_REPEATS = {
    "id":          4,
    "name":        4,
    "tags":        3,
    "description": 1,
    "code":        0,   # source code excluded from BM25 (n-gram handles fuzzy)
}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"\w+", text.lower())
    expanded: list[str] = []
    for t in tokens:
        expanded.append(t)
        expanded.extend(_SYNONYMS.get(t, []))
    return expanded


class BM25Backend(SearchBackend):
    def __init__(self):
        self._bm25: BM25Okapi | None = None
        self._widgets: list[dict] = []

    def build(self, widgets: list[dict]) -> None:
        self._widgets = widgets
        corpus = []
        for w in widgets:
            doc_tokens: list[str] = []
            for field, repeats in _FIELD_REPEATS.items():
                if repeats == 0:
                    continue
                if field == "id":
                    text = w.get("id", "").replace("-", " ")
                elif field == "name":
                    text = w.get("name", "")
                elif field == "tags":
                    text = " ".join(w.get("tags", []))
                elif field == "description":
                    text = w.get("description", "")
                else:
                    text = w.get("_code_tokens", "")
                tokens = _tokenize(text)
                doc_tokens.extend(tokens * repeats)
            corpus.append(doc_tokens)
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def score(self, query: str) -> list[float]:
        if not self._bm25:
            return [0.0] * len(self._widgets)
        return list(self._bm25.get_scores(_tokenize(query)))

    def query(self, query, domain_filter=None, language_filter=None, top_k=15):
        # This backend is used via score() in the hybrid; direct query() kept for standalone use
        from .filters import apply_filters, format_results
        scores = self.score(query)
        pairs = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in pairs:
            if score <= 0:
                break
            w = self._widgets[idx]
            if not apply_filters(w, domain_filter, language_filter):
                continue
            results.append({**w, "relevance_score": round(score, 4)})
            if len(results) >= top_k:
                break
        return format_results(results)
