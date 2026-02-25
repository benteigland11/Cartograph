"""
Widget and blueprint installation / uninstallation.

install() and uninstall() take `carto` (a Cartographer instance) as first argument.
"""

import glob
import json
import os
import shutil
import sys


DEFAULT_INSTALL_DIR = "cartographer"


def _copy_widget_files(carto, item_path, dest_path, widget, is_blueprint):
    """Copy widget/blueprint files from library to destination."""
    os.makedirs(dest_path, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")

    folders = ["src", "tests", "examples"]
    if is_blueprint:
        folders.append("widgets")
    for folder in folders:
        src = os.path.join(item_path, folder)
        dest = os.path.join(dest_path, folder)
        if os.path.exists(src):
            shutil.copytree(src, dest, dirs_exist_ok=True, ignore=ignore)

    manifest_name = "blueprint.json" if is_blueprint else "widget.json"
    manifest_src = os.path.join(item_path, manifest_name)
    if os.path.exists(manifest_src):
        shutil.copy2(manifest_src, dest_path)

    project_files = [
        "Cargo.toml", "Cargo.lock",
        "go.mod", "go.sum",
        "package.json", "package-lock.json",
        "tsconfig.json",
        "CMakeLists.txt",
        "Makefile",
        "pom.xml",
        "build.gradle",
    ]
    for pf in project_files:
        pf_src = os.path.join(item_path, pf)
        if os.path.exists(pf_src):
            shutil.copy2(pf_src, dest_path)
    for csproj in glob.glob(os.path.join(item_path, "*.csproj")):
        shutil.copy2(csproj, dest_path)

    review_src = os.path.join(item_path, "reviews.json")
    if not os.path.exists(review_src):
        review_src = os.path.join(widget["path"], "reviews.json")
    if os.path.exists(review_src):
        shutil.copy2(review_src, dest_path)


def install(carto, widget_id, target_dir, version=None, visited=None, blueprint=None):
    """Install a widget or blueprint into target_dir."""
    from cartographer import SCRIPT_DIR

    if not os.path.isabs(target_dir):
        print(f"⚠️  Warning: Relative path '{target_dir}' used.", file=sys.stderr)
    target_abs = os.path.abspath(target_dir)

    if visited is None:
        visited = set()
    if widget_id in visited:
        return {"status": "skipped", "message": f"Dependency '{widget_id}' already processed."}
    visited.add(widget_id)

    if not os.path.exists(target_abs):
        print(f"📁 Creating target directory: {target_dir}", file=sys.stderr)
        os.makedirs(target_abs, exist_ok=True)

    if not os.path.isdir(target_abs):
        return {"status": "error", "message": f"Target path is not a directory: {target_abs}"}

    if target_abs == os.path.abspath(carto.library_path) or target_abs == SCRIPT_DIR:
        return {"status": "error",
                "message": "Illegal target: cannot install into the library or tool directory."}

    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)

    if not widget:
        search_results = carto.search(widget_id, top_k=1)
        suggestions = search_results.get("library", [])
        msg = f"Widget ID '{widget_id}' not found."
        if suggestions and suggestions[0]["relevance_score"] > 1.0:
            msg += f" Did you mean '{suggestions[0]['id']}'?"
        return {"status": "error", "message": msg}

    item_path = widget["path"]
    actual_version = widget.get("version", "current")

    if version:
        history_path = os.path.join(item_path, "history", version)
        if os.path.exists(history_path):
            print(f"📜 Version Override: Installing v{version}.", file=sys.stderr)
            item_path = history_path
            actual_version = version
        else:
            return {"status": "error", "message": f"Version '{version}' not found for {widget_id}"}

    is_blueprint = widget.get("type") == "blueprint"

    if is_blueprint:
        return {"status": "error",
                "message": f"Blueprint install is not supported in v0.1. '{widget_id}' is a blueprint."}

    # --- Blueprint-targeted install: widget goes into blueprint's widgets/ dir ---
    if blueprint and not is_blueprint:
        blueprint_path = os.path.join(target_abs, "blueprints", blueprint)
        blueprint_manifest = os.path.join(blueprint_path, "blueprint.json")
        if not os.path.exists(blueprint_manifest):
            return {"status": "error", "message": f"Blueprint '{blueprint}' not found at {blueprint_path}"}

        widget_folder_name = os.path.basename(widget["path"])
        dest_path = os.path.join(blueprint_path, "widgets", widget_folder_name)

        try:
            _copy_widget_files(carto, item_path, dest_path, widget, is_blueprint=False)

            with open(blueprint_manifest) as f:
                bp_data = json.load(f)
            composed_of = bp_data.get("composed_of", [])
            if widget_id not in carto._extract_composed_ids(composed_of):
                composed_of.append({"id": widget_id, "version": actual_version})
                bp_data["composed_of"] = composed_of
                with open(blueprint_manifest, "w") as f:
                    json.dump(bp_data, f, indent=2)

            carto.installed_index.setdefault(widget_id, []).append({"path": dest_path, "type": "widget"})
            carto._increment_install_count(widget_id)

            dep_failed, dep_installed = [], []
            for dep_id in widget.get("depends_on", []):
                dep_result = install(carto, dep_id, target_dir, visited=visited, blueprint=blueprint)
                if dep_result.get("status") == "error":
                    dep_failed.append({"id": dep_id, "error": dep_result.get("message")})
                elif dep_result.get("status") == "success":
                    dep_installed.append(dep_id)

            result = {"status": "success", "installed_at": dest_path, "type": "widget",
                      "version": actual_version, "blueprint": blueprint,
                      "message": f"Installed {widget['name']} v{actual_version} into blueprint {blueprint}/widgets/"}
            if dep_failed:
                result["warning"] = f"{len(dep_failed)} dependency(s) failed to install"
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # --- Standard install ---
    if is_blueprint:
        composed_entries = carto._normalize_composed_of(widget.get("composed_of", []))
        dep_ids = [e["id"] for e in composed_entries]
    else:
        composed_entries = []
        dep_ids = widget.get("depends_on", [])

    sub_folder = "blueprints" if is_blueprint else "widgets"
    widget_folder_name = os.path.basename(widget["path"])
    dest_path = os.path.join(target_abs, sub_folder, widget_folder_name)

    failed_deps, installed_deps = [], []

    if is_blueprint:
        for entry in composed_entries:
            dep_id = entry["id"]
            dep_version = entry.get("version")
            if dep_id in visited:
                continue
            dep_widget = next((w for w in carto.widgets if w["id"] == dep_id), None)
            if not dep_widget:
                failed_deps.append({"id": dep_id, "error": f"Widget '{dep_id}' not found"})
                continue
            dep_item_path = dep_widget["path"]
            dep_actual_version = dep_widget.get("version", "current")
            if dep_version:
                dep_hist = os.path.join(dep_item_path, "history", dep_version)
                if os.path.exists(dep_hist):
                    dep_item_path = dep_hist
                    dep_actual_version = dep_version
            dep_dest = os.path.join(dest_path, "widgets", os.path.basename(dep_widget["path"]))
            try:
                _copy_widget_files(carto, dep_item_path, dep_dest, dep_widget, is_blueprint=False)
                carto.installed_index.setdefault(dep_id, []).append({"path": dep_dest, "type": "widget"})
                carto._increment_install_count(dep_id)
                installed_deps.append(dep_id)
                visited.add(dep_id)
            except Exception as e:
                failed_deps.append({"id": dep_id, "error": str(e)})
    else:
        for dep_id in dep_ids:
            res = install(carto, dep_id, target_dir, visited=visited)
            if res.get("status") == "error":
                failed_deps.append({"id": dep_id, "error": res.get("message")})
            elif res.get("status") == "success":
                installed_deps.append(dep_id)

    try:
        _copy_widget_files(carto, item_path, dest_path, widget, is_blueprint)
        carto.installed_index.setdefault(widget_id, []).append({"path": dest_path, "type": widget.get("type")})
        carto._increment_install_count(widget_id)

        result = {"status": "success", "installed_at": dest_path, "type": widget.get("type"),
                  "version": actual_version,
                  "message": f"Hydrated {widget['name']} v{actual_version} into {sub_folder}/"}
        if is_blueprint and dep_ids:
            result["dependencies"] = {"installed": installed_deps, "failed": failed_deps}
        elif not is_blueprint and failed_deps:
            result["warning"] = f"{len(failed_deps)} dependency(s) failed"
            result["failed_dependencies"] = failed_deps
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def uninstall(carto, widget_id):
    """Remove a widget from the local installation."""
    installed_info = carto._get_installed_info(widget_id)
    if not installed_info:
        return {"status": "error", "message": f"Widget '{widget_id}' is not installed."}

    if isinstance(installed_info, list):
        paths_to_remove = [info.get("path") if isinstance(info, dict) else info
                           for info in installed_info]
    else:
        paths_to_remove = [installed_info]

    base_install_dir = os.path.abspath(DEFAULT_INSTALL_DIR)
    removed_count = 0

    for path in paths_to_remove:
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(base_install_dir):
            return {"status": "error",
                    "message": f"Safety Block: Cannot uninstall {abs_path} as it is outside {base_install_dir}"}
        if os.path.exists(abs_path):
            try:
                shutil.rmtree(abs_path)
                removed_count += 1
            except Exception as e:
                return {"status": "error", "message": f"Failed to delete {abs_path}: {e}"}

    if removed_count > 0:
        carto.installed_index = carto._load_installed_index()
        return {"status": "success", "message": f"Uninstalled {widget_id} ({removed_count} location(s) removed)."}
    return {"status": "error", "message": "Installation directory not found on disk."}
