"""
Widget inspection and popularity queries.
"""

import datetime
import glob
import json
import os
import sys


def list_popular(carto, limit=10):
    sorted_widgets = sorted(carto.widgets, key=lambda x: x.get("install_count", 0), reverse=True)
    return {
        "top_assets": [
            {"id": w["id"], "name": w["name"], "version": w.get("version", "0.0.0"),
             "install_count": w.get("install_count", 0)}
            for w in sorted_widgets[:limit]
        ]
    }


def _read_dir(dirpath, prefix_filter=None):
    """Read files in a directory into a {filename: content} dict.

    prefix_filter: if given, only include filenames whose basename starts with that string.
    """
    out = {}
    if os.path.exists(dirpath):
        for fpath in glob.glob(os.path.join(dirpath, "*.*")):
            name = os.path.basename(fpath)
            if prefix_filter and not name.startswith(prefix_filter):
                continue
            try:
                with open(fpath) as f:
                    out[name] = f.read()
            except Exception as e:
                out[name] = f"Error reading: {e}"
    return out


def _get_versions(widget_path, all_versions=False):
    """Return version list from history/ directory, newest first."""
    history_dir = os.path.join(widget_path, "history")
    if not os.path.exists(history_dir):
        return []
    versions = sorted(os.listdir(history_dir), reverse=True)
    if all_versions:
        return versions
    return versions[:5]


def inspect(carto, widget_id, show_source=False, show_all_versions=False,
            show_reviews=False, version=None):
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": "Widget not found"}

    widget_path = widget["path"]

    if version is not None:
        history_path = os.path.join(widget_path, "history", version)
        if not os.path.exists(history_path):
            available = _get_versions(widget_path, all_versions=True)
            return {"error": f"Version '{version}' not found. Available: {', '.join(available) or 'none'}"}
        read_path = history_path
    else:
        read_path = widget_path

    # Reviews always come from current widget, not history
    review_data = carto._load_reviews(widget_path)

    try:
        with open(os.path.join(read_path, "widget.json")) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        manifest = {}
    meta = manifest.get("meta", manifest)

    result = {
        "id": widget["id"],
        "name": meta.get("name", widget["name"]),
        "description": manifest.get("description", widget["description"]),
        "language": manifest.get("tech_stack", {}).get("language", widget.get("language", "unknown")),
        "domain": meta.get("domain", widget["domain"]),
        "version": meta.get("version", version or widget.get("version", "0.0.0")),
        "dependencies": manifest.get("tech_stack", {}).get("dependencies", widget.get("dependencies", [])),
        "rating": review_data["rating"],
        "trend": review_data.get("trend"),
        "review_count": review_data["count"],
        "versions": _get_versions(widget_path, all_versions=show_all_versions),
        "examples": _read_dir(os.path.join(read_path, "examples"), prefix_filter="example_usage"),
        "usage_hints": _read_dir(os.path.join(read_path, "examples"), prefix_filter="usage_hint"),
    }

    if show_source:
        result["source"] = _read_dir(os.path.join(read_path, "src"))
    if show_reviews:
        result["reviews"] = review_data["reviews"]

    return result


def log_registration(carto, widget_id, widget_name, similar_widgets, differentiation, needs_review, widget_path):
    from .engine import CARTOGRAPH_DIR, EXTRACTION_LOG_PATH
    os.makedirs(CARTOGRAPH_DIR, exist_ok=True)
    log = {"extractions": []}
    if os.path.exists(EXTRACTION_LOG_PATH):
        try:
            with open(EXTRACTION_LOG_PATH) as f:
                log = json.load(f)
        except Exception:
            pass
    log["extractions"].append({
        "widget_id": widget_id,
        "widget_name": widget_name,
        "timestamp": datetime.datetime.now().isoformat(),
        "needs_review": needs_review,
        "similar_widgets_found": [{"id": w["id"], "relevance_score": w["relevance_score"]}
                                   for w in similar_widgets],
        "differentiation": differentiation or None,
        "widget_path": widget_path,
    })
    with open(EXTRACTION_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)
