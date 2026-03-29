"""
Widget installation and uninstallation.
"""

import glob
import json
import os
import shutil
import zipfile
from io import BytesIO


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


def _widget_dir(target_dir, widget_id):
    """Return the install path: <project_root>/cartograph/<dir_name>.
    Python widgets get underscores so the directory is importable."""
    from .engine import python_dir_name
    from .engine import DEFAULT_INSTALL_DIR
    return os.path.join(target_dir, DEFAULT_INSTALL_DIR, python_dir_name(widget_id))


def _install_from_cloud(widget_id, dest_path):
    """Search cloud for a widget and install it by downloading the zip."""
    from .cloud import search as cloud_search, download_widget

    # Search cloud to find the widget and its owner
    results = cloud_search(widget_id, top_k=5)
    widgets = results.get("widgets", [])
    match = next((w for w in widgets if w.get("id") == widget_id), None)
    if not match:
        return {"error": f"Widget '{widget_id}' not found locally or in the cloud registry."}

    owner = match.get("owner", "")
    if not owner:
        return {"error": f"Widget '{widget_id}' found in cloud but missing owner info."}

    result = download_widget(owner, widget_id)
    if "error" in result:
        return result

    # Extract zip to destination
    zip_bytes = result["zip_bytes"]
    version = result.get("version", "0.0.0")
    try:
        os.makedirs(dest_path, exist_ok=True)
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            zf.extractall(dest_path)
        return {
            "status": "success",
            "widget_id": widget_id,
            "version": version,
            "installed_at": dest_path,
            "source": "cloud",
        }
    except Exception as e:
        # Clean up partial install
        shutil.rmtree(dest_path, ignore_errors=True)
        return {"error": f"Failed to extract widget: {e}"}


def install(carto, widget_id, target_dir, version=None):
    """Install a widget into target_dir/cartograph/widget_id."""
    from .engine import REPO_DIR

    if not os.path.isabs(target_dir):
        return {"error": f"Target must be an absolute path, got: '{target_dir}'"}

    from .engine import PACKAGE_DIR
    if target_dir == os.path.abspath(carto.library_path):
        return {"error": f"Cannot install into the widget library ({carto.library_path})."}
    if os.path.abspath(target_dir) == os.path.dirname(PACKAGE_DIR):
        return {"error": f"Cannot install into the engine source directory ({os.path.dirname(PACKAGE_DIR)})."}

    dest_path = _widget_dir(target_dir, widget_id)

    if os.path.exists(dest_path):
        return {"error": f"'{widget_id}' already installed at {dest_path}. Uninstall first to reinstall."}

    # Try local library first
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if widget:
        source_path = widget["path"]
        installed_version = widget.get("version", "0.0.0")

        if version:
            history_path = os.path.join(source_path, "history", version)
            if not os.path.exists(history_path):
                return {"error": f"Version '{version}' not found for '{widget_id}'."}
            source_path = history_path
            installed_version = version

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

    # Fall back to cloud registry
    return _install_from_cloud(widget_id, dest_path)


def upgrade(carto, widget_id, target_dir, version=None):
    """Upgrade an installed widget to the latest (or specific) version."""
    dest_path = _widget_dir(target_dir, widget_id)
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


def delete_from_library(carto, widget_id, confirm=False):
    """Permanently remove a widget from the library."""
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": f"Widget '{widget_id}' not found. Use 'cartograph search' to find available widgets."}

    install_count = widget.get("install_count", 0)

    if not confirm:
        return {
            "status": "dry_run",
            "widget_id": widget_id,
            "version": widget.get("version", "unknown"),
            "install_count": install_count,
            "library_path": widget["path"],
            "message": "No changes made. Re-run with --confirm to permanently delete.",
        }

    widget_path = widget["path"]
    try:
        shutil.rmtree(widget_path)
    except Exception as e:
        return {"error": f"Failed to delete: {e}"}

    if widget_id in carto.install_stats:
        del carto.install_stats[widget_id]
        carto._save_install_stats()

    return {
        "status": "success",
        "widget_id": widget_id,
        "deleted_from": widget_path,
        "install_count_at_deletion": install_count,
    }


def uninstall(carto, widget_id, target_dir):
    """Remove an installed widget from target_dir/cartograph/widget_id."""
    if not os.path.isabs(target_dir):
        return {"error": f"Target must be an absolute path, got: '{target_dir}'"}

    widget_path = _widget_dir(target_dir, widget_id)

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
