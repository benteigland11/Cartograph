"""
Shared filtering and result formatting used by all backends.
"""

from __future__ import annotations


def apply_filters(widget: dict, domain_filter: str | None,
                  language_filter: str | None, type_filter: str | None) -> bool:
    """Return True if the widget passes all active filters."""
    # Domain
    if domain_filter and domain_filter != "all":
        if widget["domain"] != domain_filter and widget["domain"] != "universal":
            return False

    # Language
    if language_filter:
        w_lang = widget.get("language", "")
        filter_val = language_filter.lower()
        if isinstance(w_lang, list):
            w_langs = {l.lower() for l in w_lang}
        else:
            w_langs = {l.strip().lower()
                       for l in str(w_lang).replace(",", " ").replace("/", " ").split()}
        if filter_val not in w_langs:
            return False

    # Type
    if type_filter and type_filter != "all":
        if widget.get("type", "widget") != type_filter:
            return False

    return True


def format_results(scored_widgets: list[dict]) -> dict:
    """Split scored results into installed vs library buckets."""
    installed, library = [], []

    for res in scored_widgets:
        score = res["relevance_score"]

        if res.get("is_installed"):
            installed_info = res.get("installed_at", [])
            if isinstance(installed_info, list) and installed_info:
                inst_path = (installed_info[0].get("path")
                             if isinstance(installed_info[0], dict) else installed_info[0])
            else:
                inst_path = str(installed_info)
            installed.append({
                "id": res["id"], "name": res["name"], "version": res["version"],
                "path": inst_path, "relevance_score": score,
            })
        else:
            display_name = res["name"]
            if res.get("regression"):
                display_name = f"⚠️ {res['name']} (REGRESSION IN {res['version']})"
            library.append({
                "id": res["id"],
                "name": display_name,
                "version": res["version"],
                "description": res["description"],
                "language": res.get("language", "unknown"),
                "dependencies": res.get("dependencies", []),
                "domain": res["domain"],
                "maturity": res.get("maturity", "unknown"),
                "rating": res.get("rating", 0),
                "install_count": res.get("install_count", 0),
                "tags": res.get("tags", []),
                "relevance_score": score,
                "test_count": res.get("test_count", 0),
                "lines_of_code": res.get("lines_of_code", 0),
                "widget_type": res.get("widget_type", "library"),
                "gpu_targets": res.get("gpu_targets", []),
            })

    return {"installed": installed, "library": library}
