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


def format_results(scored_widgets: list[dict]) -> dict:
    """Format scored widgets into a flat results list."""
    results = []
    for res in scored_widgets:
        results.append({
            "id": res["id"],
            "name": res["name"],
            "version": res.get("version", "0.0.0"),
            "description": res["description"],
            "language": res.get("language", "unknown"),
            "domain": res["domain"],
            "dependencies": res.get("dependencies", []),
            "rating": res.get("rating", 0),
            "install_count": res.get("install_count", 0),
            "relevance_score": res["relevance_score"],
        })
    return {"results": results}
