"""
Hybrid BM25 + n-gram search engine.

Combines two complementary signals for local, in-memory search:
  - BM25    : whole-token matching, good for natural-language queries
  - N-gram  : character-level fuzzy matching, good for typos and partial matches

Final score = α * norm(bm25) + β * norm(ngram) + optional exact-match boost.

Both score vectors are normalised to [0, 1] before combining so neither
dominates by accident of scale.

Usage:
    engine = HybridSearch(fields={"name": 4.0, "description": 1.0, "tags": 2.0})
    engine.index(documents)
    results = engine.search("auth middleware", top_k=10)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


# ============================================================================
# N-gram index
# ============================================================================

def _ngrams(text: str, n: int) -> set[str]:
    """Return the set of character n-grams in text."""
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i: i + n] for i in range(len(text) - n + 1)}


def _field_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> set[str]:
    """Union of bigrams and trigrams for a piece of text."""
    grams: set[str] = set()
    for n in sizes:
        grams |= _ngrams(text, n)
    return grams


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ============================================================================
# BM25
# ============================================================================

class _BM25:
    """Minimal BM25Okapi implementation — no external dependencies."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._corpus: list[list[str]] = []
        self._doc_len: list[int] = []
        self._avgdl: float = 0.0
        self._df: Counter[str] = Counter()
        self._n_docs: int = 0

    def build(self, corpus: list[list[str]]) -> None:
        self._corpus = corpus
        self._n_docs = len(corpus)
        self._doc_len = [len(doc) for doc in corpus]
        self._avgdl = sum(self._doc_len) / self._n_docs if self._n_docs else 1.0
        self._df = Counter()
        for doc in corpus:
            unique = set(doc)
            for token in unique:
                self._df[token] += 1

    def _idf(self, token: str) -> float:
        df = self._df.get(token, 0)
        return math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str]) -> list[float]:
        scores = []
        for i, doc in enumerate(self._corpus):
            tf_map: Counter[str] = Counter(doc)
            doc_score = 0.0
            for token in query_tokens:
                tf = tf_map.get(token, 0)
                idf = self._idf(token)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * self._doc_len[i] / self._avgdl)
                doc_score += idf * numerator / denominator
            scores.append(doc_score)
        return scores


# ============================================================================
# Tokenizer
# ============================================================================

def _tokenize(text: str, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    tokens = re.findall(r"\w+", text.lower())
    if not synonyms:
        return tokens
    expanded: list[str] = []
    for t in tokens:
        expanded.append(t)
        expanded.extend(synonyms.get(t, []))
    return expanded


# ============================================================================
# Normalisation
# ============================================================================

def _normalise(scores: list[float]) -> list[float]:
    """Min-max normalise to [0, 1]. Returns zeros if all scores are equal."""
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [0.0] * len(scores)
    span = hi - lo
    return [(s - lo) / span for s in scores]


# ============================================================================
# Hybrid search engine
# ============================================================================

class HybridSearch:
    """
    A hybrid BM25 + n-gram fuzzy search engine.

    Args:
        fields: Dict mapping field names to their weight (higher = more important).
                Fields with weight 0 are excluded from BM25 but included in n-gram.
        bm25_weight: Contribution of BM25 to the final score (0-1).
        ngram_weight: Contribution of n-gram to the final score (0-1).
        exact_boost: Score boost for exact substring matches in high-weight fields.
        synonyms: Optional dict mapping tokens to synonym lists for query expansion.
    """

    def __init__(
        self,
        fields: dict[str, float] | None = None,
        bm25_weight: float = 0.4,
        ngram_weight: float = 0.6,
        exact_boost: float = 0.3,
        synonyms: dict[str, list[str]] | None = None,
    ):
        self.fields = fields or {"name": 3.0, "description": 1.0, "tags": 2.0}
        self.bm25_weight = bm25_weight
        self.ngram_weight = ngram_weight
        self.exact_boost = exact_boost
        self.synonyms = synonyms

        self._bm25 = _BM25()
        self._documents: list[dict[str, Any]] = []
        self._ngram_index: list[dict[str, set[str]]] = []
        self._high_weight_fields: list[str] = []

    def index(self, documents: list[dict[str, Any]]) -> None:
        """Build the search index from a list of documents (dicts with string fields)."""
        self._documents = documents
        self._high_weight_fields = [f for f, w in self.fields.items() if w >= 2.0]

        # Build BM25 corpus
        corpus: list[list[str]] = []
        for doc in documents:
            doc_tokens: list[str] = []
            for field, weight in self.fields.items():
                if weight == 0:
                    continue
                text = self._get_field_text(doc, field)
                tokens = _tokenize(text, self.synonyms)
                repeat = max(1, int(weight))
                doc_tokens.extend(tokens * repeat)
            corpus.append(doc_tokens)
        self._bm25.build(corpus)

        # Build n-gram index
        self._ngram_index = []
        for doc in documents:
            entry: dict[str, set[str]] = {}
            for field in self.fields:
                text = self._get_field_text(doc, field)
                entry[field] = _field_ngrams(text)
            self._ngram_index.append(entry)

    def search(
        self,
        query: str,
        top_k: int = 15,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search the indexed documents.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.
            filters: Optional dict of {field: value} to filter documents.

        Returns:
            List of matching documents with a "score" field added, sorted by relevance.
        """
        if not self._documents:
            return []

        # Score with both backends
        bm25_raw = self._bm25.score(_tokenize(query, self.synonyms))
        ngram_raw = self._ngram_score(query)

        bm25_norm = _normalise(bm25_raw)
        ngram_norm = _normalise(ngram_raw)

        query_lower = query.lower()
        scored: list[dict[str, Any]] = []

        for idx, doc in enumerate(self._documents):
            combined = (self.bm25_weight * bm25_norm[idx] +
                        self.ngram_weight * ngram_norm[idx])

            # Exact substring boost on high-weight fields
            for field in self._high_weight_fields:
                text = self._get_field_text(doc, field).lower()
                if query_lower in text:
                    combined += self.exact_boost
                    break

            if combined <= 0:
                continue

            # Apply filters
            if filters and not self._matches_filters(doc, filters):
                continue

            scored.append({**doc, "score": round(combined, 4)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _ngram_score(self, query: str) -> list[float]:
        """Return a weighted n-gram score for every document."""
        query_grams = _field_ngrams(query)
        scores: list[float] = []
        for entry in self._ngram_index:
            weighted = sum(
                self.fields[field] * _jaccard(query_grams, entry[field])
                for field in self.fields
            )
            scores.append(weighted)
        return scores

    @staticmethod
    def _get_field_text(doc: dict[str, Any], field: str) -> str:
        """Extract text from a document field, handling lists."""
        value = doc.get(field, "")
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
        return str(value)

    @staticmethod
    def _matches_filters(doc: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if a document matches all filters."""
        for key, value in filters.items():
            doc_value = doc.get(key)
            if isinstance(doc_value, str) and isinstance(value, str):
                if doc_value.lower() != value.lower():
                    return False
            elif doc_value != value:
                return False
        return True
