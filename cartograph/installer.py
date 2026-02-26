"""
Widget installation and uninstallation.
"""

import glob
import json
import os
import shutil


def _copy_widget(source_path, dest_path):
    """Copy widget files from library to destination."""
    os.makedirs(dest_path, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")

    for folder in ("src", "tests", "examples"):
        src = os.path.join(source_path, folder)
        if os.path.exists(src):
            shutil.copytree(src, os.path.join(dest_path, folder),
                            dirs_exist_ok=True, ignore=ignore)

    # widget.json
    manifest = os.path.join(source_path, "widget.json")
    if os.path.exists(manifest):
        shutil.copy2(manifest, dest_path)

    # Language project files
    for name in ("Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
                 "package.json", "package-lock.json", "tsconfig.json",
                 "CMakeLists.txt", "Makefile", "pom.xml", "build.gradle"):
        path = os.path.join(source_path, name)
        if os.path.exists(path):
            shutil.copy2(path, dest_path)
    for csproj in glob.glob(os.path.join(source_path, "*.csproj")):
        shutil.copy2(csproj, dest_path)


def install(carto, widget_id, target_dir, version=None):
    """Install a widget into target_dir."""
    from .engine import REPO_DIR

    if not os.path.isabs(target_dir):
        return {"error": f"Target must be an absolute path, got: '{target_dir}'"}

    if target_dir == os.path.abspath(carto.library_path) or target_dir == REPO_DIR:
        return {"error": "Cannot install into the library or engine directory."}

    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": f"Widget '{widget_id}' not found."}

    source_path = widget["path"]
    installed_version = widget.get("version", "0.0.0")

    if version:
        history_path = os.path.join(source_path, "history", version)
        if not os.path.exists(history_path):
            return {"error": f"Version '{version}' not found for '{widget_id}'."}
        source_path = history_path
        installed_version = version

    dest_path = os.path.join(target_dir, widget_id)

    if os.path.exists(dest_path):
        return {"error": f"'{widget_id}' already installed at {dest_path}. Uninstall first to reinstall."}

    try:
        _copy_widget(source_path, dest_path)
        carto._increment_install_count(widget_id)
        return {
            "status": "success",
            "widget_id": widget_id,
            "version": installed_version,
            "installed_at": dest_path,
        }
    except Exception as e:
        return {"error": str(e)}


def update(carto, widget_id, target_dir, version=None):
    """Update an installed widget to the latest (or specific) version."""
    dest_path = os.path.join(target_dir, widget_id)
    if not os.path.exists(dest_path):
        return {"error": f"'{widget_id}' not found at {dest_path}. Install it first."}

    # Read current version before removing
    old_version = "unknown"
    try:
        with open(os.path.join(dest_path, "widget.json")) as f:
            old_version = json.load(f).get("meta", {}).get("version", "unknown")
    except Exception:
        pass

    # Remove old copy
    result = uninstall(carto, widget_id, target_dir)
    if "error" in result:
        return result

    # Install new copy (install won't bump install count again for updates)
    result = install(carto, widget_id, target_dir, version=version)
    if "error" in result:
        return result

    result["previous_version"] = old_version
    return result


def uninstall(carto, widget_id, target_dir):
    """Remove an installed widget from target_dir."""
    if not os.path.isabs(target_dir):
        return {"error": f"Target must be an absolute path, got: '{target_dir}'"}

    widget_path = os.path.join(target_dir, widget_id)

    if not os.path.exists(widget_path):
        return {"error": f"'{widget_id}' not found at {widget_path}."}

    # Safety: must be inside the target dir
    if not os.path.abspath(widget_path).startswith(os.path.abspath(target_dir)):
        return {"error": f"Safety check failed: path escapes target directory."}

    try:
        shutil.rmtree(widget_path)
        return {"status": "success", "widget_id": widget_id, "removed_from": widget_path}
    except Exception as e:
        return {"error": f"Failed to remove: {e}"}
