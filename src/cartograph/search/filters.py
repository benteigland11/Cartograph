"""
Shared filtering and result formatting used by all backends.
"""

from __future__ import annotations

from ..engine import normalize_language


def apply_filters(widget: dict, domain_filter: str | None,
                  language_filter: str | None) -> bool:
    """Return True if the widget passes all active filters."""
    if domain_filter and domain_filter != "all":
        if widget["domain"] != domain_filter and widget["domain"] != "universal":
            return False

    if language_filter:
        filter_val = normalize_language(language_filter)
        w_lang = widget.get("language", "")
        if isinstance(w_lang, list):
            w_langs = {normalize_language(l) for l in w_lang}
        else:
            w_langs = {normalize_language(l)
                       for l in str(w_lang).replace(",", " ").replace("/", " ").split()}
        if filter_val not in w_langs:
            return False

    return True


# Results at or below this score had no query term in any widget name/id.
# It's the max possible combined score without the exact-match boost (see hybrid.py).
# Below it = normalized noise; above it = at least one term found in name or id.
_EXACT_BOOST_THRESHOLD = 1.0

# When no exact match exists, cap results to avoid token bloat on noise.
_LOW_CONFIDENCE_LIMIT = 3

# --- Small-corpus bypass ---
# BM25 uses IDF: log((N - n + 0.5) / (n + 0.5)).  When the library has
# fewer than ~10 widgets, most terms appear in a large fraction of docs and
# IDF collapses toward 0.  This zeros out the BM25 component, capping the
# max combined score at ~0.9 (n-gram + exact boost) — below the 1.0
# threshold above.  Net effect: search returns nothing even for exact
# matches.
#
# Below this size we skip the strict threshold and return anything that
# passed the backend's own _MIN_SCORE (0.10).  Once the library grows past
# this point, the full threshold kicks in automatically.
_SMALL_CORPUS_THRESHOLD = 10


def format_results(scored_widgets: list[dict], corpus_size: int = 0) -> dict:
    """Format scored widgets into a flat results list.

    If the top score exceeds _EXACT_BOOST_THRESHOLD, at least one query term
    appeared in a widget name or id — return up to top_k results.
    For small corpora (< _SMALL_CORPUS_THRESHOLD), return whatever the
    backend matched — BM25 IDF is unreliable at that scale.
    """
    results = []
    for res in scored_widgets:
        entry = {
            "id": res.get("namespaced_id") or res["id"],
            "name": res["name"],
            "version": res.get("version", "0.0.0"),
            "description": res["description"],
            "language": res.get("language", "unknown"),
            "domain": res["domain"],
            "dependencies": res.get("dependencies", []),
            "rating": res.get("rating", 0),
            "trend": res.get("trend"),
            "install_count": res.get("install_count", 0),
            "relevance_score": res["relevance_score"],
        }
        results.append(entry)

    if corpus_size > 0 and corpus_size < _SMALL_CORPUS_THRESHOLD:
        return {"results": results}

    top_score = scored_widgets[0]["relevance_score"] if scored_widgets else 0
    if top_score <= _EXACT_BOOST_THRESHOLD:
        return {"results": [], "message": "No results found. Try broader or simpler terms — single keywords, synonyms, or the core concept."}
    # High confidence: still apply a floor to drop noise below the exact match
    return {"results": [r for r in results if r["relevance_score"] >= _EXACT_BOOST_THRESHOLD * 0.3]}
