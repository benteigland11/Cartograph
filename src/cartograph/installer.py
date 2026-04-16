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
    for nimble in glob.glob(os.path.join(source_path, "*.nimble")):
        shutil.copy2(nimble, dest_path)


def _widget_dir(target_dir, widget_id):
    """Return the install path: <project_root>/cg/<dir_name>.
    Python widgets get underscores so the directory is importable."""
    from .engine import python_dir_name
    from .engine import DEFAULT_INSTALL_DIR
    return os.path.join(target_dir, DEFAULT_INSTALL_DIR, python_dir_name(widget_id))


def _resolve_registry(widget_id: str):
    """Check if widget_id starts with a known registry prefix.

    Returns (registry_url, prefix, bare_widget_id) if a prefix is recognized,
    or None if no prefix matches (caller uses default local-first behavior).
    """
    from .config import get_registries, _PUBLIC_REGISTRY_PREFIX, _PUBLIC_REGISTRY_URL

    if widget_id.startswith(_PUBLIC_REGISTRY_PREFIX + "-"):
        bare_id = widget_id[len(_PUBLIC_REGISTRY_PREFIX) + 1:]
        return _PUBLIC_REGISTRY_URL, _PUBLIC_REGISTRY_PREFIX, bare_id

    for reg in get_registries():
        prefix = reg["prefix"]
        if widget_id.startswith(prefix + "-"):
            bare_id = widget_id[len(prefix) + 1:]
            return reg["url"], prefix, bare_id

    return None


def _install_from_cloud(widget_id, dest_path, registry_url=None, owner_hint=None):
    """Search cloud for a widget and install it by downloading the zip."""
    from .cloud import download_widget

    if owner_hint:
        # Already know the owner from @owner/widget_id format
        owner = owner_hint
    else:
        # Search cloud to find the widget and its owner
        from .cloud import search as cloud_search
        results = cloud_search(widget_id, top_k=5, registry_url=registry_url)
        widgets = results.get("widgets", [])
        match = next(
            (w for w in widgets
             if w.get("id") == widget_id
             or w.get("id", "").endswith(f"/{widget_id}")),
            None,
        )
        if not match:
            registry_label = registry_url or "the cloud registry"
            return {"error": f"Widget '{widget_id}' not found locally or in {registry_label}."}
        owner = match.get("owner", "")
        if not owner:
            return {"error": f"Widget '{widget_id}' found in cloud but missing owner info."}

    result = download_widget(owner, widget_id, registry_url=registry_url)
    if "error" in result:
        return result

    # Extract zip to destination
    zip_bytes = result["zip_bytes"]
    version = result.get("version", "0.0.0")
    try:
        os.makedirs(dest_path, exist_ok=True)
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            zf.extractall(dest_path)

        # Write sidecar so checkin knows where this came from
        from .auth import get_registry_url as _public_url
        source_meta = {
            "owner": owner,
            "registry_url": registry_url or _public_url(),
        }
        with open(os.path.join(dest_path, ".cartograph_source"), "w") as f:
            json.dump(source_meta, f)

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


def install(carto, widget_id, target_dir, version=None,
            _owner_hint=None, _registry_url=None):
    """Install a widget into target_dir/cg/<widget_id>.

    If widget_id has a known registry prefix (e.g. cg-foo, myorg-foo), the
    install goes directly to that registry and skips the local library.
    Unprefixed IDs use the existing local-first then cloud-fallback behavior.

    _owner_hint and _registry_url are internal params used by upgrade() to
    re-install the correct owner's widget from the correct registry.
    """
    # Strip @owner/ prefix if present (cloud widget IDs are namespaced)
    owner_hint = _owner_hint
    if widget_id.startswith("@"):
        parts = widget_id[1:].split("/", 1)
        if len(parts) == 2:
            owner_hint, widget_id = parts

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

    # Explicit registry prefix: skip local library, go directly to that registry.
    # dest_path keeps the prefixed name (cg/cg-widget-name/) so prefixed and
    # local installs coexist without collision.
    resolved = _resolve_registry(widget_id)
    if resolved is not None:
        registry_url, _prefix, bare_id = resolved
        from .config import cloud_enabled
        if not cloud_enabled():
            return {"error": "Cloud is disabled. Enable it with: cartograph config cloud true"}
        return _install_from_cloud(bare_id, dest_path, registry_url=registry_url,
                                   owner_hint=owner_hint)

    # No prefix: try local library first
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

    # Fall back to cloud registry if enabled
    from .config import cloud_enabled
    if not cloud_enabled():
        return {"error": f"Widget '{widget_id}' not found in local library."}
    return _install_from_cloud(widget_id, dest_path, registry_url=_registry_url,
                               owner_hint=owner_hint)


def _upgrade_backup_path(widget_id: str) -> str:
    """Return the path to the single-slot upgrade backup for widget_id."""
    from .engine import _user_data_dir
    return os.path.join(_user_data_dir(), "upgrade-backup", widget_id)


def upgrade(carto, widget_id, target_dir, version=None):
    """Upgrade an installed widget to the latest (or specific) version.

    Backs up the current installation before removing it. If the new install
    fails, the backup is restored so the widget is never left in a broken state.
    """
    dest_path = _widget_dir(target_dir, widget_id)
    if not os.path.exists(dest_path):
        return {"error": f"'{widget_id}' not found at {dest_path}. Install it first."}

    # Read current version and sidecar before removing
    old_version = "unknown"
    try:
        with open(os.path.join(dest_path, "widget.json")) as f:
            old_version = json.load(f).get("meta", {}).get("version", "unknown")
    except Exception:
        pass

    source_meta = {}
    try:
        with open(os.path.join(dest_path, ".cartograph_source")) as f:
            source_meta = json.load(f)
    except Exception:
        pass

    # Back up current installation to a single-slot holding area
    backup_path = _upgrade_backup_path(widget_id)
    try:
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        shutil.copytree(dest_path, backup_path)
    except Exception as e:
        return {"error": f"Could not create upgrade backup: {e}"}

    # Remove old copy
    result = uninstall(carto, widget_id, target_dir)
    if "error" in result:
        shutil.rmtree(backup_path, ignore_errors=True)
        return result

    # Install new copy — pass owner and registry from sidecar so we upgrade
    # the correct owner's widget, not just the highest-ranked search result
    owner_hint = source_meta.get("owner") or None
    registry_url = source_meta.get("registry_url") or None
    result = install(carto, widget_id, target_dir, version=version,
                     _owner_hint=owner_hint, _registry_url=registry_url)
    if "error" in result:
        # Restore from backup
        try:
            shutil.copytree(backup_path, dest_path)
        except Exception as restore_err:
            result["restore_error"] = str(restore_err)
            result["backup_path"] = backup_path
        else:
            result["restored"] = True
            result["restored_version"] = old_version
        shutil.rmtree(backup_path, ignore_errors=True)
        return result

    # Success — clean up backup
    shutil.rmtree(backup_path, ignore_errors=True)
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
    """Remove an installed widget from target_dir/cg/widget_id."""
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
