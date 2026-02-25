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
            {"id": w["id"], "name": w["name"], "version": w["version"],
             "install_count": w.get("install_count", 0),
             "type": w.get("type", "widget"), "maturity": w.get("maturity", "unknown")}
            for w in sorted_widgets[:limit]
        ]
    }


def inspect(carto, widget_id, show_examples=False, show_source=False, show_tests=False, version=None):
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": "Widget not found"}

    result = {k: v for k, v in widget.items() if k != "path"}
    widget_path = widget["path"]

    if version:
        history_path = os.path.join(widget_path, "history", version)
        if os.path.exists(history_path):
            print(f"📜 Inspecting historical v{version} for {widget_id}", file=sys.stderr)
            widget_path = history_path
            manifest_name = "blueprint.json" if widget["type"] == "blueprint" else "widget.json"
            try:
                with open(os.path.join(widget_path, manifest_name)) as f:
                    result[f"metadata_v{version}"] = json.load(f)
            except Exception:
                pass
        else:
            return {"error": f"Version '{version}' not found in history for {widget_id}"}

    history_dir = os.path.join(widget["path"], "history")
    if os.path.exists(history_dir):
        result["history"] = os.listdir(history_dir)

    changelog_path = os.path.join(widget["path"], "changelog.json")
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path) as f:
                result["changelog"] = json.load(f)
        except Exception:
            pass

    result["stats"] = {
        "files": {
            "src": len(glob.glob(os.path.join(widget_path, "src", "*.*"))),
            "tests": len(glob.glob(os.path.join(widget_path, "tests", "*.*"))),
            "examples": len(glob.glob(os.path.join(widget_path, "examples", "*.*"))),
        }
    }
    total_lines = 0
    for src_file in glob.glob(os.path.join(widget_path, "src", "*.*")):
        try:
            with open(src_file) as f:
                total_lines += len(f.readlines())
        except Exception:
            pass
    result["stats"]["lines_of_code"] = total_lines

    if not (show_examples or show_source or show_tests):
        result["hint"] = "Use --examples, --source, --tests, or --all for more details"
        return result

    def _read_dir(dirpath):
        out = {}
        if os.path.exists(dirpath):
            for fpath in glob.glob(os.path.join(dirpath, "*.*")):
                try:
                    with open(fpath) as f:
                        out[os.path.basename(fpath)] = f.read()
                except Exception as e:
                    out[os.path.basename(fpath)] = f"Error reading file: {e}"
        return out or {"note": "No files found"}

    if show_examples:
        result["examples"] = _read_dir(os.path.join(widget_path, "examples"))
    if show_source:
        result["source"] = _read_dir(os.path.join(widget_path, "src"))
    if show_tests:
        result["tests"] = _read_dir(os.path.join(widget_path, "tests"))

    return result


def log_registration(carto, widget_id, widget_name, similar_widgets, differentiation, needs_review, widget_path):
    from cartographer import CARTOGRAPHER_DIR, EXTRACTION_LOG_PATH
    os.makedirs(CARTOGRAPHER_DIR, exist_ok=True)
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
