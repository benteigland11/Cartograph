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
import glob
import json
import logging
import os
import re
import shutil
import sys

log = logging.getLogger("cartograph")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "library_config.json")


def _canonical_library_notes(language: str, domain: str = "") -> dict:
    """Return the authoritative library_notes for a given language and domain."""
    try:
        with open(_CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        return {}
    notes = {
        "general": cfg.get("general_notes", ""),
        "language": cfg.get("language_notes", {}).get(language.lower(), ""),
    }
    domain_note = cfg.get("domain_notes", {}).get(domain.lower(), "")
    if domain_note:
        notes["domain"] = domain_note
    return notes


def _restore_library_notes(manifest_path: str) -> None:
    """Overwrite library_notes in widget.json with the canonical version.

    Called just before copying to the library so agents cannot drift or
    remove the library-wide standards even if they edited widget.json.
    """
    try:
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
    except Exception:
        pass  # non-fatal — checkin proceeds


# ---------------------------------------------------------------------------
# Contamination scanner
# ---------------------------------------------------------------------------

_ABS_PATH_RE = re.compile(
    r'["\'](?:/home/|/Users/|/root/|[A-Za-z]:[/\\\\])[^"\']{3,}["\']'
)

_CREDENTIAL_RE = re.compile(
    r'(?:api_key|api_secret|secret_key|access_token|auth_token|password|passwd|credential)\s*=\s*["\'][^"\']{6,}["\']',
    re.IGNORECASE,
)

_ENVVAR_RE = re.compile(r'os\.getenv\(|os\.environ')

_URL_RE = re.compile(
    r'["\']https?://(?!(?:localhost|127\.0\.0\.1|(?:[\w-]+\.)*example\.com|schemas?\.))[^"\']{8,}["\']'
)

_IP_RE = re.compile(r'["\'](?:\d{1,3}\.){3}\d{1,3}(?::\d+)?["\']')

_IMPORT_RE = re.compile(r'^\s*(?:import|from)\s+([\w.]+)', re.MULTILINE)

_STDLIB = sys.stdlib_module_names  # complete, maintained by Python itself (3.10+)


def _scan_contamination(path: str, widget: dict) -> dict:
    """
    Scan Python source files for project-specific contamination.
    Returns {"blocks": [...], "warnings": [...]}.
    """
    blocks, warnings = [], []

    # Collect declared dependency names for import check
    deps = widget.get("dependencies", [])
    dep_names = set()
    for d in deps:
        name = d if isinstance(d, str) else d.get("name", "")
        # strip extras [opt] and version specifiers >=, ==, ~=, etc.
        bare = re.split(r'[><=!~;\[]', name)[0].strip().lower()
        if bare:
            dep_names.add(bare)

    # Widget's own module names (everything under src/)
    own_modules = set()
    src_dir = os.path.join(path, "src")
    if os.path.isdir(src_dir):
        for f in os.listdir(src_dir):
            if f.endswith(".py"):
                own_modules.add(f[:-3])

    src_files = glob.glob(os.path.join(path, "src", "**", "*.py"), recursive=True)
    all_files = src_files + glob.glob(os.path.join(path, "tests", "**", "*.py"), recursive=True)

    for fpath in all_files:
        rel = os.path.relpath(fpath, path)
        try:
            code = open(fpath).read()
        except Exception:
            continue

        for line_no, line in enumerate(code.splitlines(), 1):
            loc = f"{rel}:{line_no}"

            # src/: hard block on paths and credentials
            # tests/: warn on credentials (might be real), ignore paths (always fake)
            if fpath in src_files:
                if _ABS_PATH_RE.search(line):
                    blocks.append(f"Absolute path in {loc}: {line.strip()}")
                if _CREDENTIAL_RE.search(line):
                    blocks.append(f"Possible credential in {loc}: {line.strip()}")
            else:
                if _CREDENTIAL_RE.search(line):
                    warnings.append(f"Possible credential in test {loc} — verify it's fake: {line.strip()}")

        for m in _ENVVAR_RE.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            warnings.append(f"os.environ/getenv call in {rel}:{line_no} — verify it's not project-specific")

        for m in _URL_RE.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            warnings.append(f"Hardcoded URL in {rel}:{line_no}: {m.group()}")

        for m in _IP_RE.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            warnings.append(f"Hardcoded IP in {rel}:{line_no}: {m.group()}")

        if fpath in src_files:
            for m in _IMPORT_RE.finditer(code):
                top = m.group(1).split(".")[0].lower()
                if top and top not in _STDLIB and top not in dep_names and top not in own_modules:
                    line_no = code[:m.start()].count("\n") + 1
                    warnings.append(
                        f"Unlisted import '{top}' in {rel}:{line_no} — add to dependencies or remove"
                    )

    return {"blocks": blocks, "warnings": warnings}


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

    # --- Validate ---
    val = carto.validate_item(path)
    if val["status"] != "success":
        return val

    # --- Check for outdated base version ---
    widget_record = next((w for w in carto.widgets if w["id"] == item_id), None)
    if widget_record:
        local_version = meta.get("version", "0.0.0")
        library_version = widget_record.get("version", "0.0.0")
        if local_version != library_version:
            return {
                "status": "error",
                "message": f"Version conflict: local is v{local_version} but library is v{library_version}. "
                           f"Install the latest version first, apply your changes, then checkin."
            }

    # --- Contamination scan ---
    scan = _scan_contamination(path, data.get("tech_stack", {}))

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
                       "Review warnings and re-run with override_warnings=True and override_reason=<explanation>.",
            "warnings": scan["warnings"],
        }

    if override_warnings and not override_reason:
        return {"status": "error", "message": "override_reason is required when override_warnings=True"}

    # --- Determine update vs new ---
    is_update = widget_record is not None

    # --- Version bump (only on updates, not first checkin) ---
    version = meta.get("version", "1.0.0")
    if is_update:
        parts = version.split(".")
        if len(parts) == 3:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            if version_bump == "major":
                major, minor, patch = major + 1, 0, 0
            elif version_bump == "minor":
                minor, patch = minor + 1, 0
            elif version_bump == "patch":
                patch += 1
            new_version = f"{major}.{minor}.{patch}"
        else:
            new_version = version
    else:
        new_version = version

    data["meta"]["version"] = new_version
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
        os.makedirs(history_path, exist_ok=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "history", "changelog.json")
        for item in os.listdir(dest_path):
            if item in ("history", "changelog.json"):
                continue
            src = os.path.join(dest_path, item)
            dst = os.path.join(history_path, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=ignore)
            else:
                shutil.copy2(src, dst)

    # --- Restore library_notes before copying (agent edits ignored) ---
    _restore_library_notes(manifest_path)

    # --- Copy working copy → library (never move — leave source intact) ---
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    os.makedirs(dest_path, exist_ok=True)
    for item in os.listdir(path):
        if item in ("history", "changelog.json", "__pycache__", ".pytest_cache"):
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

    # --- Reload library so the in-memory index reflects the new widget ---
    carto._load_library()
    carto._search_backend.build(carto.widgets)

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
    temp_dir = os.path.join(os.getcwd(), f"_restore_{item_id}")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    shutil.copytree(history_path, temp_dir)

    current_version = item.get("version", "1.0.0")
    parts = current_version.split(".")
    if len(parts) == 3:
        parts[-1] = str(int(parts[-1]) + 1)
        next_version = ".".join(parts)
    else:
        next_version = current_version + ".1"

    manifest_path = os.path.join(temp_dir, "widget.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["meta"]["version"] = next_version
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    result = checkin(carto, temp_dir, reason=f"RESTORE from v{version}: {reason}",
                     version_bump="patch")
    shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def add_review(carto, widget_id, target_dir, score, comment=None):
    """Add a review to a widget. Must be installed at target_dir/widget_id/."""
    installed_path = os.path.join(target_dir, "cartograph", widget_id)
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

    review_entry = {
        "rating": score,
        "version": widget.get("version", "unknown"),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if comment:
        review_entry["comment"] = comment

    review_path = os.path.join(widget["path"], "reviews.json")
    reviews_data = {"reviews": []}
    if os.path.exists(review_path):
        try:
            with open(review_path) as f:
                reviews_data = json.load(f)
        except Exception:
            pass

    reviews_data["reviews"].append(review_entry)
    with open(review_path, "w") as f:
        json.dump(reviews_data, f, indent=2)

    return {"status": "success", "widget_id": widget_id, "score": score}


def widget_status(carto, widget_id, target_dir):
    """Check the status of an installed widget against the library."""
    widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
    if not widget:
        return {"error": f"'{widget_id}' not found in library."}

    installed_path = os.path.join(target_dir, "cartograph", widget_id)
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

    return {
        "widget_id": widget_id,
        "installed_version": installed_version,
        "library_version": library_version,
        "outdated": outdated,
        "modified": modified,
    }
