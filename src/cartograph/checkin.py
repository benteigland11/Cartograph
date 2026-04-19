"""
Check-in workflow: push edits from an installed widget back to the library.

Primary flow:
    install(widget_id) → edit files in place → checkin(path, reason="why")

checkin() auto-detects the widget ID from widget.json and whether it already
exists in the library (update) or is new. It scans for project-specific
contamination before accepting anything.

Contamination scanning
----------------------
Hard blocks (checkin fails, no override):
  - Absolute paths baked into source strings (/home/, /Users/, C:\\, C:/)
  - Apparent credential assignments (api_key = "...", token = "abc123", etc.)

Warnings (checkin pauses, agent must pass override_warnings=True + override_reason):
  - os.getenv / os.environ calls
  - Hardcoded non-local URLs / IP addresses
  - Imports that aren't stdlib, listed dependencies, or the widget's own src/

On override the reason is recorded in the changelog entry as an audit trail.
"""

import datetime
import json
import logging
import os
import shutil

from .engine import semver_key as _semver_key
from .languages import get_engine
from .scaffolding import _library_notes as _canonical_library_notes
from .validation_stamp import is_stamp_valid, write_stamp, STAMP_FILE as _STAMP_FILE

log = logging.getLogger("cartograph")


def _restore_library_notes(manifest_path: str) -> None:
    """Overwrite library_notes in widget.json with the canonical version.

    Called just before copying to the library so agents cannot drift or
    remove the library-wide standards even if they edited widget.json.
    """
    with open(manifest_path) as f:
        data = json.load(f)
    language = data.get("tech_stack", {}).get("language", "")
    if isinstance(language, list):
        language = language[0] if language else ""
    domain = data.get("meta", {}).get("domain", "")
    canonical = _canonical_library_notes(language, domain)
    if canonical:
        data["library_notes"] = canonical
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=2)


# Contamination scanning is now in contamination.py, delegated to per-language engines.
# Kept as import alias for backwards compatibility within this module.
from .contamination import scan_contamination as _scan_contamination


def _lookup_cloud_baseline(path: str, item_id: str) -> dict | None:
    """Return {"version": ..., "implementation_hash": ..., "source": "cloud"} if a
    `.cartograph_source` sidecar points at a cloud record for this widget, else None.

    `implementation_hash` is only populated when the registry echoes it back in the
    inspect response (issue #15). When present, it lets the no-op guard and the
    three-way status view run against the cloud baseline without downloading the
    widget zip. When absent, callers fall back to their pre-echo behavior gracefully.

    Sidecar-only: we don't probe the cloud for widgets that weren't installed
    from it. Falls back silently when offline, unauthenticated, or the widget
    isn't resolvable there.
    """
    sidecar_path = os.path.join(path, ".cartograph_source")
    if not os.path.isfile(sidecar_path):
        return None
    try:
        with open(sidecar_path) as f:
            source = json.load(f)
    except Exception:
        return None
    owner = source.get("owner")
    registry_url = source.get("registry_url")
    if not owner:
        return None
    try:
        from . import cloud, auth
        if not cloud.is_available():
            return None
    except Exception:
        return None
    try:
        remote = cloud.inspect(owner, item_id, registry_url=registry_url)
    except Exception:
        return None
    if not remote or remote.get("error"):
        return None
    version = remote.get("version")
    if not version:
        return None
    result = {"version": version, "source": "cloud"}
    impl_hash = remote.get("implementation_hash")
    if impl_hash:
        result["implementation_hash"] = impl_hash
    return result


# ---------------------------------------------------------------------------
# checkin
# ---------------------------------------------------------------------------

def checkin(carto, path: str, reason: str = "", version_bump: str = "minor",
            override_warnings: bool = False, override_reason: str = "") -> dict:
    """
    Push an edited widget back to the library.

    Detects update vs new from whether the widget ID already exists in the
    library. Never deletes or moves the source — the installed copy is left
    intact after a successful checkin.

    Args:
        path:              Directory containing widget.json and src/
        reason:            Human/agent description of what changed
        version_bump:      "major" | "minor" | "patch"  (default "minor")
        override_warnings: Pass True to proceed despite contamination warnings
        override_reason:   Required when override_warnings=True — recorded in changelog
    """
    if not os.path.isdir(path):
        return {"status": "error", "message": f"Path not found: {path}"}

    # --- Read manifest ---
    manifest_path = os.path.join(path, "widget.json")
    if not os.path.exists(manifest_path):
        return {"status": "error", "message": "No widget.json found."}

    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "error", "message": f"Invalid widget.json: {e}"}

    meta = data.get("meta", {})
    item_id = meta.get("id", "").strip()
    if not item_id:
        return {"status": "error", "message": "widget.json is missing meta.id"}

    # --- Validate (skip if a fresh stamp exists) ---
    tech_stack = data.get("tech_stack", {})
    language = tech_stack.get("language", "python").lower()
    engine = get_engine(language)
    if engine and is_stamp_valid(path, language, engine):
        log.info("Validation stamp is fresh — skipping re-validation")
    else:
        val = carto.validate_item(path)
        if val["status"] != "success":
            return val

    # --- Resolve bump baseline: cloud (via sidecar) wins over local library ---
    # If a .cartograph_source sidecar exists, the widget was installed from the
    # cloud and cloud is the source of truth for "what version exists." Local
    # library is the fallback when there's no sidecar.
    widget_record = next((w for w in carto.widgets if w["id"] == item_id), None)
    cloud_baseline = _lookup_cloud_baseline(path, item_id)

    baseline_version = None
    baseline_source = None
    if cloud_baseline:
        baseline_version = cloud_baseline["version"]
        baseline_source = "cloud"
    elif widget_record:
        baseline_version = widget_record.get("version", "0.0.0")
        baseline_source = "library"

    if baseline_version is not None:
        local_version = meta.get("version", "0.0.0")
        if local_version != baseline_version:
            return {
                "status": "error",
                "message": f"Version conflict: local is v{local_version} but {baseline_source} is v{baseline_version}. "
                           f"Install the latest version first, apply your changes, then checkin."
            }
        # --- No-op guard ---
        # Runs against whichever baseline we resolved, as long as that baseline
        # has an implementation_hash to compare against. Library always does;
        # cloud does once the registry starts echoing it (issue #15). If the
        # cloud baseline has no hash yet, the guard is silently skipped for
        # that case — no false-positive bumps, no missed real changes.
        if cloud_baseline:
            baseline_hash = cloud_baseline.get("implementation_hash")
        else:
            baseline_hash = widget_record.get("implementation_hash")
        if baseline_hash:
            current_hash = carto._calculate_implementation_hash(path)
            if current_hash == baseline_hash:
                return {
                    "status": "error",
                    "message": f"{item_id} v{baseline_version} is already in the {baseline_source} with identical content. "
                               f"Make your changes before checking in."
                }

    # --- Contamination scan ---
    scan = _scan_contamination(path)

    if scan["blocks"]:
        return {
            "status": "error",
            "message": "Checkin blocked: project-specific content detected.",
            "blocks": scan["blocks"],
        }

    if scan["warnings"] and not override_warnings:
        return {
            "status": "warnings",
            "message": "Checkin paused: potential contamination found. "
                       "Review warnings below, then re-run with "
                       "--override-warnings --override-reason \"<why these warnings are acceptable>\".",
            "warnings": scan["warnings"],
        }

    if override_warnings and not override_reason:
        return {"status": "error",
                "message": "--override-reason is required when using --override-warnings."}

    # --- Determine update vs new ---
    # is_update still controls local file placement (dest path, archive) and must
    # reflect whether a local library copy exists. Bumping is gated separately
    # on baseline_version — which includes cloud — so a widget known only to
    # cloud still gets bumped correctly.
    is_update = widget_record is not None
    should_bump = baseline_version is not None

    # --- Version bump (whenever a baseline exists, local or cloud) ---
    version = meta.get("version", "1.0.0")
    if should_bump:
        try:
            from packaging.version import Version as _Version
            parsed = _Version(version)
            major, minor, patch = parsed.major, parsed.minor, parsed.micro
        except Exception:
            return {"status": "error", "message": f"Cannot bump malformed version '{version}'. Fix widget.json meta.version to X.Y.Z first."}
        if version_bump == "major":
            major, minor, patch = major + 1, 0, 0
        elif version_bump == "minor":
            minor, patch = minor + 1, 0
        elif version_bump == "patch":
            patch += 1
        new_version = f"{major}.{minor}.{patch}"
    else:
        new_version = version

    data["meta"]["version"] = new_version

    # --- Stamp validation metadata into widget.json ---
    validation_block = {
        "engine_version": getattr(engine, "validation_version", None),
        "validated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if engine:
        rv = engine.runtime_version()
        if rv:
            validation_block["runtime"] = rv
    data["validation"] = validation_block

    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2)

    # --- Determine destination ---
    if is_update:
        dest_path = widget_record["path"]
    else:
        folder_name = item_id
        dest_path = os.path.join(carto.library_path, folder_name)
        if os.path.exists(dest_path):
            return {"status": "error",
                    "message": f"Directory already exists but widget is not in index: {dest_path}"}

    # --- Archive current library version to history/ ---
    if is_update and os.path.exists(dest_path):
        old_version = widget_record.get("version", "unknown")
        history_path = os.path.join(dest_path, "history", old_version)
        if os.path.exists(history_path):
            shutil.rmtree(history_path)
        os.makedirs(history_path, exist_ok=True)
        ignore = shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache",
            "node_modules", "package-lock.json",
            "history", "changelog.json", _STAMP_FILE, ".cartograph_source",
        )
        for item in os.listdir(dest_path):
            if item in ("history", "changelog.json", _STAMP_FILE, ".cartograph_source",
                        "node_modules", "package-lock.json"):
                continue
            src = os.path.join(dest_path, item)
            dst = os.path.join(history_path, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=ignore)
            else:
                shutil.copy2(src, dst)

    # --- Restore library_notes before copying (agent edits ignored) ---
    try:
        _restore_library_notes(manifest_path)
    except Exception as e:
        return {"status": "error", "message": f"Could not restore canonical library_notes: {e}"}

    # --- Copy working copy → library (never move — leave source intact) ---
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "node_modules",
                                    "package-lock.json", ".cartograph_source")
    os.makedirs(dest_path, exist_ok=True)
    for item in os.listdir(path):
        if item in ("history", "changelog.json", "__pycache__", ".pytest_cache", _STAMP_FILE,
                    ".cartograph_source", "node_modules", "package-lock.json"):
            continue
        src = os.path.join(path, item)
        dst = os.path.join(dest_path, item)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=ignore)
        else:
            shutil.copy2(src, dst)

    # --- Changelog ---
    changelog_entry = {
        "version": new_version,
        "reason": reason or ("No reason provided" if is_update else "Initial release"),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if override_warnings and override_reason:
        changelog_entry["override_reason"] = override_reason

    changelog_path = os.path.join(dest_path, "changelog.json")
    changelog = []
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path) as f:
                changelog = json.load(f)
        except Exception:
            pass
    changelog.insert(0, changelog_entry)
    with open(changelog_path, "w") as f:
        json.dump(changelog, f, indent=2)

    # --- Diff for AI review ---
    diff = carto._diff_against_library(path, item_id) if is_update else None

    # --- Write fresh stamp at library path (files are in final state) ---
    if engine:
        try:
            write_stamp(dest_path, language, engine)
        except OSError as e:
            log.warning("Could not write validation stamp after checkin: %s", e)

    # --- Reload library so the in-memory index reflects the new widget ---
    carto.reload()

    action = "updated" if is_update else "registered"
    log.info("Successfully %s %s → v%s", action, item_id, new_version)

    result = {
        "status": "success",
        "id": item_id,
        "version": new_version,
        "action": action,
        "path": dest_path,
    }
    if scan["warnings"] and override_warnings:
        result["overridden_warnings"] = scan["warnings"]
        result["override_reason"] = override_reason
    if diff:
        result["diff"] = diff
        result["diff_prompt"] = (
            "Review this diff for any remaining project-specific code, hardcoded values, "
            "or patterns that would break generic reuse."
        )
    return result


# ---------------------------------------------------------------------------
# restore, add_review, widget_status
# ---------------------------------------------------------------------------

def restore(carto, item_id, version, reason):
    """Restore a historical version to become the new head."""
    item = next((w for w in carto.widgets if w["id"] == item_id), None)
    if not item:
        return {"status": "error", "message": f"Item '{item_id}' not found"}

    history_path = os.path.join(item["path"], "history", version)
    if not os.path.exists(history_path):
        return {"status": "error", "message": f"Version '{version}' not found in history for {item_id}"}

    # Copy history version to a temp dir, then checkin as update
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix=f"cartograph_restore_{item_id}_")
    shutil.rmtree(temp_dir)  # mkdtemp creates it, copytree needs it to not exist
    shutil.copytree(history_path, temp_dir)

    # Set manifest version to current library version so the version guard
    # passes, then checkin() bumps it normally (patch).
    current_version = item.get("version", "1.0.0")
    manifest_path = os.path.join(temp_dir, "widget.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["meta"]["version"] = current_version
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    result = checkin(carto, temp_dir, reason=f"RESTORE from v{version}: {reason}",
                     version_bump="patch")
    shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def _get_reviewer() -> str:
    """Return the authenticated user's handle, or empty string."""
    try:
        from .auth import is_authenticated
        if is_authenticated():
            from .cloud import whoami
            profile = whoami()
            return profile.get("owner", "") or profile.get("username", "")
    except Exception:
        pass
    return ""


def write_review(widget_path: str, score: float, version: str,
                 comment: str | None = None) -> dict:
    """Write a review entry to reviews.json at *widget_path*. Returns result dict."""
    author = _get_reviewer()
    entry = {
        "rating": score,
        "version": version,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if author:
        entry["author"] = author
    if comment:
        entry["comment"] = comment

    review_path = os.path.join(widget_path, "reviews.json")
    reviews_data = {"reviews": []}
    if os.path.exists(review_path):
        try:
            with open(review_path) as f:
                reviews_data = json.load(f)
        except Exception:
            pass

    reviews_data["reviews"].append(entry)
    with open(review_path, "w") as f:
        json.dump(reviews_data, f, indent=2)

    avg = sum(r["rating"] for r in reviews_data["reviews"]) / len(reviews_data["reviews"])
    return {"status": "success", "rating": score, "avg_rating": round(avg, 1), "author": author}


def add_review(carto, widget_id, target_dir, score, comment=None):
    """Add a review to a widget. Must be installed at target_dir/widget_id/."""
    from .engine import python_dir_name, DEFAULT_INSTALL_DIR
    installed_path = os.path.join(target_dir, DEFAULT_INSTALL_DIR, python_dir_name(widget_id))
    if not os.path.exists(installed_path):
        return {"error": f"'{widget_id}' not found at {installed_path}. Install it first."}

    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": f"Widget '{widget_id}' not found in library."}

    try:
        score = float(score)
        if not (1 <= score <= 5):
            raise ValueError
    except (ValueError, TypeError):
        return {"error": "Score must be a number between 1 and 5."}

    return write_review(widget["path"], score, widget.get("version", "unknown"), comment)


def widget_status(carto, widget_id, target_dir):
    """Check the status of an installed widget against the library."""
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": f"'{widget_id}' not found in library."}

    from .engine import python_dir_name, DEFAULT_INSTALL_DIR
    installed_path = os.path.join(target_dir, DEFAULT_INSTALL_DIR, python_dir_name(widget_id))
    if not os.path.exists(installed_path):
        return {"error": f"'{widget_id}' not found at {installed_path}."}

    try:
        with open(os.path.join(installed_path, "widget.json")) as f:
            installed_version = json.load(f).get("meta", {}).get("version", "unknown")
    except Exception as e:
        return {"error": f"Failed to read installed manifest: {e}"}

    library_version = widget.get("version", "0.0.0")
    installed_hash = carto._calculate_implementation_hash(installed_path)
    library_hash = widget.get("implementation_hash")

    outdated = installed_version != library_version
    modified = installed_hash != library_hash

    # Cloud three-way comparison — populated when the installed copy has a
    # sidecar AND the registry echoes implementation_hash (issue #15). Without
    # the echo we still surface cloud_version; modified_vs_cloud stays absent.
    cloud_info = _lookup_cloud_baseline(installed_path, widget_id) or {}
    cloud_version = cloud_info.get("version")
    cloud_hash = cloud_info.get("implementation_hash")

    return {
        "widget_id": widget_id,
        "installed_version": installed_version,
        "library_version": library_version,
        "cloud_version": cloud_version,
        **({"outdated_vs_cloud": installed_version != cloud_version}
           if cloud_version else {}),
        **({"modified_vs_cloud": installed_hash != cloud_hash}
           if cloud_hash else {}),
        "outdated": outdated,
        "modified": modified,
    }
