"""
Check-in workflow: submit, version, restore, review, and compare widgets.

All public functions take `carto` (a Cartographer instance) as the first argument
so they can access the in-memory widget index and shared helpers without circular imports.
"""

import datetime
import glob
import json
import os
import shutil
import sys


def checkin_item(carto, path, differentiation="", update=True, reason="", version_bump="minor"):
    """Validate and move an item into the library. Removes local copy on success."""
    from cartographer import PENDING_WIDGETS_PATH

    val = carto.validate_item(path)
    if val["status"] != "success":
        return val

    manifest_path = os.path.join(path, "widget.json")
    item_type = "widget"
    if not os.path.exists(manifest_path):
        manifest_path = os.path.join(path, "blueprint.json")
        item_type = "blueprint"

    with open(manifest_path) as f:
        data = json.load(f)
    meta = data.get("meta", {})
    item_id = meta["id"]
    item_name = meta["name"]
    domain = meta["domain"]
    tags = meta.get("tags", [])
    version = meta.get("version", "1.0.0")

    # Auto version bump
    if update and version_bump:
        parts = version.split(".")
        if len(parts) == 3:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            if version_bump == "major":
                major, minor, patch = major + 1, 0, 0
            elif version_bump == "minor":
                major, minor, patch = major, minor + 1, 0
            elif version_bump == "patch":
                major, minor, patch = major, minor, patch + 1
            version = f"{major}.{minor}.{patch}"
            data["meta"]["version"] = version
            with open(manifest_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"📦 Version bumped to {version} ({version_bump})", file=sys.stderr)

    # Auto-append language suffix to ID
    if item_type == "widget":
        language = data.get("tech_stack", {}).get("language", "")
        if isinstance(language, list):
            language = language[0] if language else "unknown"
        normalized_lang = carto._normalize_language(language)
        if not item_id.endswith(f"-{normalized_lang}"):
            item_id = f"{item_id}-{normalized_lang}"
            data["meta"]["id"] = item_id
            with open(manifest_path, "w") as f:
                json.dump(data, f, indent=2)

    # Diff review
    diff_review = carto._diff_against_library(path, item_id) if update else None

    # Duplicate detection (new items only)
    high_similarity = []
    needs_review = False

    if not update:
        print(f"\n🔍 Checking for duplicates in {item_type}s...", file=sys.stderr)
        if item_type == "widget":
            current_hash = carto._calculate_implementation_hash(path)
            exact = next((w for w in carto.widgets if w.get("implementation_hash") == current_hash), None)
            if exact:
                return {"status": "error",
                        "message": f"Identical code already exists in widget '{exact['id']}'"}
        if item_type == "blueprint":
            current_comps = set(carto._extract_composed_ids(data.get("composed_of", [])))
            exact = next((w for w in carto.widgets
                          if w["type"] == "blueprint"
                          and set(carto._extract_composed_ids(w.get("composed_of", []))) == current_comps), None)
            if exact:
                return {"status": "error",
                        "message": f"A blueprint with identical components already exists: {exact['id']}"}

        search_query = f"{item_name} {' '.join(tags)}"
        search_result = carto.search(search_query, domain_filter=domain, top_k=5)
        candidates = search_result.get("library", []) + search_result.get("installed", [])
        similar = [w for w in candidates if w.get("type", "widget") == item_type]
        high_similarity = [w for w in similar if w["relevance_score"] > 2.0]
        needs_review = len(high_similarity) > 0

    # Determine destination
    if item_type == "widget":
        target_lib = PENDING_WIDGETS_PATH if needs_review else carto.library_path
    else:
        target_lib = PENDING_WIDGETS_PATH if needs_review else carto.blueprint_path

    existing_item = next((w for w in carto.widgets if w["id"] == item_id), None)
    if existing_item and update:
        dest_path = existing_item["path"]
    else:
        folder_name = item_id.replace("-", ".", 1)
        dest_path = os.path.join(target_lib, folder_name)

    changelog_entry = {
        "version": version,
        "reason": reason or ("No reason provided" if update else "Initial release"),
        "timestamp": datetime.datetime.now().isoformat(),
    }

    if os.path.exists(dest_path):
        if update:
            current_manifest = "blueprint.json" if item_type == "blueprint" else "widget.json"
            try:
                with open(os.path.join(dest_path, current_manifest)) as f:
                    old_version = json.load(f).get("meta", {}).get("version", "unknown")
                history_path = os.path.join(dest_path, "history", old_version)
                os.makedirs(history_path, exist_ok=True)
                print(f"🔄 UPDATING: Archiving v{old_version} to history...", file=sys.stderr)
                for item in os.listdir(dest_path):
                    if item in ("history", "changelog.json"):
                        continue
                    shutil.move(os.path.join(dest_path, item), history_path)
            except Exception as e:
                print(f"⚠️  Warning: Could not archive old version: {e}", file=sys.stderr)
                shutil.rmtree(dest_path)
        else:
            return {"status": "error",
                    "message": f"Item already exists in library: {dest_path}. Use --update to overwrite."}

    data["meta"]["needs_review"] = needs_review
    if differentiation:
        data["meta"]["differentiation"] = differentiation
    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2)

    # Changelog
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    resolved_path = os.path.realpath(path)
    is_install_dir = (os.sep + "cartographer" + os.sep + "widgets" + os.sep in resolved_path or
                      os.sep + "cartographer" + os.sep + "blueprints" + os.sep in resolved_path)

    if update:
        os.makedirs(dest_path, exist_ok=True)
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

        for item in os.listdir(path):
            if item in ("history", "changelog.json", "__pycache__", ".pytest_cache"):
                continue
            s = os.path.join(path, item)
            d = os.path.join(dest_path, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True, ignore=ignore)
            else:
                shutil.copy2(s, d)

        if is_install_dir:
            print(f"📦 Source is in install directory — left in place: {path}", file=sys.stderr)
        else:
            checkedin_dir = os.path.join(os.path.dirname(path), "checkedin")
            os.makedirs(checkedin_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.move(path, os.path.join(checkedin_dir, f"{item_id}_{version}_{ts}"))
            print(f"📦 Checkout archived to checkedin/", file=sys.stderr)
    else:
        with open(os.path.join(path, "changelog.json"), "w") as f:
            json.dump([changelog_entry], f, indent=2)
        os.makedirs(target_lib, exist_ok=True)
        if is_install_dir:
            shutil.copytree(path, dest_path, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.move(path, dest_path)

    carto._log_registration(item_id, item_name, high_similarity, differentiation, needs_review, dest_path)

    print(f"\n✅ Successfully {'updated' if update else 'registered'} {item_id}!", file=sys.stderr)
    result = {"status": "success", "path": dest_path, "needs_review": needs_review,
              "action": "update" if update else "register"}
    if diff_review:
        result["diff_review"] = diff_review
        result["ai_review_prompt"] = ("Review the diff for project-specific code, hardcoded paths, "
                                      "credentials, or non-generic patterns.")
    return result


def restore(carto, item_id, version, reason):
    """Restore a historical version to become the new head."""
    item = next((w for w in carto.widgets if w["id"] == item_id), None)
    if not item:
        return {"status": "error", "message": f"Item '{item_id}' not found"}

    history_path = os.path.join(item["path"], "history", version)
    if not os.path.exists(history_path):
        return {"status": "error", "message": f"Version '{version}' not found in history for {item_id}"}

    print(f"🔄 RESTORE: Promoting v{version} of {item_id} to HEAD...")

    temp_dir = os.path.join(os.getcwd(), f"temp_restore_{item_id}")
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

    manifest_name = "blueprint.json" if item["type"] == "blueprint" else "widget.json"
    manifest_path = os.path.join(temp_dir, manifest_name)
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["meta"]["version"] = next_version
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    result = checkin_item(carto, temp_dir, update=True,
                          reason=f"RESTORE: {reason} (Promoted from v{version})")
    if result["status"] == "success":
        print(f"🚀 Restored {item_id} to v{next_version} (from v{version})", file=sys.stderr)
    return result


def add_review(carto, item_id_or_path, rating, comment, author="AI", version=None):
    """Add a review. Path-based (proof of installation) or ID-based."""
    item_id = item_id_or_path

    if os.path.exists(item_id_or_path):
        for fname in ("widget.json", "blueprint.json"):
            mp = os.path.join(item_id_or_path, fname)
            if os.path.exists(mp):
                try:
                    with open(mp) as f:
                        local_data = json.load(f)
                    meta = local_data.get("meta", {})
                    item_id = meta.get("id")
                    version = meta.get("version")
                except Exception as e:
                    return {"status": "error", "message": f"Failed to read local manifest: {e}"}
                break
        else:
            return {"status": "error", "message": f"No widget/blueprint.json at {item_id_or_path}"}
    else:
        return {"status": "error", "message": "Rating requires a local install path (proof of installation)."}

    widget = next((w for w in carto.widgets if w["id"] == item_id), None)
    if not widget:
        return {"status": "error", "message": f"Item '{item_id}' not found in library."}

    try:
        rating = float(rating)
        if not (1 <= rating <= 5):
            raise ValueError
    except (ValueError, TypeError):
        return {"status": "error", "message": "Rating must be a number between 1 and 5"}

    review_entry = {
        "author": author,
        "rating": rating,
        "comment": comment,
        "version": version or widget.get("version", "unknown"),
        "timestamp": datetime.datetime.now().isoformat(),
    }

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

    return {"status": "success", "message": f"Added {rating}★ review to {item_id}", "item_id": item_id}


def compare_versions(carto, item_id):
    """Compare an installed widget's version and integrity to the library."""
    widget = next((w for w in carto.widgets if w["id"] == item_id), None)
    if not widget:
        return {"status": "error", "message": f"Item '{item_id}' not found in library"}

    installed_paths = carto._get_installed_info(item_id)
    if not installed_paths:
        return {"status": "not_installed", "message": f"Item '{item_id}' is not installed",
                "library_version": widget.get("version", "current")}

    if isinstance(installed_paths, list) and installed_paths:
        installed_path = (installed_paths[0].get("path")
                          if isinstance(installed_paths[0], dict) else installed_paths[0])
    else:
        installed_path = installed_paths

    manifest_name = "blueprint.json" if widget.get("type") == "blueprint" else "widget.json"
    try:
        with open(os.path.join(installed_path, manifest_name)) as f:
            installed_meta = json.load(f).get("meta", {})
            installed_version = installed_meta.get("version", "unknown")
    except Exception as e:
        return {"status": "error", "message": f"Failed to read installed manifest: {e}"}

    library_version = widget.get("version", "current")
    installed_hash = carto._calculate_implementation_hash(installed_path)
    library_hash = widget.get("implementation_hash")

    if installed_version != library_version:
        status = "outdated"
    elif installed_hash != library_hash:
        status = "modified"
    else:
        status = "clean"

    changelog_path = os.path.join(widget["path"], "CHANGELOG.md")
    changelog_content = ""
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path) as f:
                changelog_content = f.read()
        except Exception:
            pass

    return {
        "status": status,
        "item_id": item_id,
        "name": widget.get("name"),
        "domain": widget.get("domain"),
        "installed_version": installed_version,
        "library_version": library_version,
        "changelog": changelog_content[:1000] if changelog_content else "No changelog available",
    }


def compare_all_installed(carto):
    """Compare all installed widgets/blueprints to their library versions."""
    from cartographer import DEFAULT_INSTALL_DIR

    if not os.path.exists(DEFAULT_INSTALL_DIR):
        return {"status": "empty", "total_installed": 0,
                "message": f"No installations found ('{DEFAULT_INSTALL_DIR}' does not exist)."}

    clean, modified, outdated = [], [], []

    def _process(res):
        bucket = {"id": res["item_id"], "name": res["name"],
                  "domain": res["domain"], "version": res.get("installed_version")}
        if res["status"] == "clean":
            clean.append(bucket)
        elif res["status"] == "modified":
            modified.append(bucket)
        elif res["status"] == "outdated":
            outdated.append({**bucket, "library_version": res["library_version"]})

    for subdir, manifest_name in [("widgets", "widget.json"), ("blueprints", "blueprint.json")]:
        d = os.path.join(DEFAULT_INSTALL_DIR, subdir)
        if not os.path.exists(d):
            continue
        for folder in os.listdir(d):
            mp = os.path.join(d, folder, manifest_name)
            if not os.path.exists(mp):
                continue
            try:
                with open(mp) as f:
                    item_id = json.load(f).get("meta", {}).get("id")
                if item_id:
                    res = compare_versions(carto, item_id)
                    if res.get("status") not in (None, "error"):
                        _process(res)
            except Exception:
                pass

    total = len(clean) + len(modified) + len(outdated)
    pct = lambda n: round((n / total * 100) if total > 0 else 0, 1)
    return {
        "status": "success", "total_installed": total,
        "clean": clean, "clean_count": len(clean),
        "modified": modified, "modified_count": len(modified),
        "outdated": outdated, "outdated_count": len(outdated),
        "summary": {"clean_percent": pct(len(clean)), "modified_percent": pct(len(modified)),
                    "outdated_percent": pct(len(outdated))},
    }
