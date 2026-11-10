"""Machine-local usage ledger.

Records which widget was installed, upgraded, removed, or noted, for which
project, and why. The file lives under the Cartograph data directory.
Search and inspect read it. Nothing in this module is sent to a registry.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone

from cg.data_jsonl_ledger_python.src.jsonl_ledger import append, forget, read

LEDGER_ENV = "CARTOGRAPH_USAGE_LEDGER"
MAX_RECORDS = 2000
MAX_LINE_BYTES = 4096
MAX_PURPOSE = 200
PRIOR_LIMIT = 5
GIT_TIMEOUT_SECONDS = 2
LOCK_TIMEOUT_SECONDS = 30
RECORD_ACTIONS = frozenset({"install", "upgrade", "uninstall", "note"})

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def ledger_path() -> str:
    """Return the ledger file path.

    ``CARTOGRAPH_USAGE_LEDGER``, when set, is the whole path. Otherwise the
    file is ``<data-dir>/.state/usage-ledger.jsonl``.
    """
    override = os.environ.get(LEDGER_ENV)
    if override:
        return override
    from .engine import _user_data_dir
    return os.path.join(_user_data_dir(), ".state", "usage-ledger.jsonl")


def ledger_enabled() -> bool:
    """Return whether new reads for search and new writes are on."""
    from .config import get_value
    value, err = get_value("usage-ledger")
    if err:
        return True
    return bool(value)


def project_identity(project_root: str) -> dict:
    """Return path, origin remote, and project key for ``project_root``.

    The key is the origin URL with one trailing slash and a trailing
    ``.git`` removed. SSH and HTTPS URLs stay distinct. When git has no
    origin, the key is the real path.
    """
    path = os.path.realpath(os.path.abspath(project_root))
    remote = _git_origin(path)
    if remote:
        key = normalize_remote(remote)
    else:
        key = path
    return {
        "project_path": path,
        "project_remote": remote,
        "project_key": key,
    }


def normalize_remote(remote: str) -> str:
    """Strip surrounding space, one trailing slash, and a trailing ``.git``."""
    text = remote.strip()
    if text.endswith("/"):
        text = text[:-1]
    if text.endswith(".git"):
        text = text[:-4]
    return text


def normalize_purpose(raw: str | None) -> str | None:
    """Collapse whitespace and enforce the length cap.

    Empty input becomes None. A value longer than ``MAX_PURPOSE`` raises
    ValueError. Newlines become spaces.
    """
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if not text:
        return None
    if len(text) > MAX_PURPOSE:
        raise ValueError(f"purpose must be at most {MAX_PURPOSE} characters")
    return text


def parse_widget_token(token: str) -> tuple[str, str | None]:
    """Return ``(canonical_id, owner)`` from an install token.

    ``@owner/cg-foo-python`` yields ``("cg-foo-python", "owner")``.
    """
    from .engine import normalize_widget_id
    text = (token or "").strip()
    owner = None
    if text.startswith("@"):
        owner, _, text = text[1:].partition("/")
        owner = owner or None
    return normalize_widget_id(text), owner


def bare_id(widget_id: str, prefixes: list[str]) -> str:
    """Strip ``@owner/`` and the longest matching registry prefix."""
    base = widget_id.split("/", 1)[-1]
    if base.startswith("@"):
        base = base[1:]
    for prefix in sorted((p for p in prefixes if p), key=len, reverse=True):
        head = prefix + "-"
        if base.startswith(head):
            return base[len(head):]
    return base


def record_usage(
    action: str,
    *,
    widget_id: str,
    version: str | None,
    purpose: str | None,
    project_root: str,
    owner: str | None = None,
    previous_version: str | None = None,
    carry_purpose: bool = False,
) -> dict | None:
    """Append one usage event.

    Returns None when the ledger is disabled (callers omit the field).
    Returns ``{"recorded": False, "error": ...}`` when the write fails.
    The caller decides whether that failure fails the command.
    """
    if not ledger_enabled():
        return None
    if action not in RECORD_ACTIONS:
        return {"recorded": False, "error": f"unknown action: {action}"}
    try:
        canonical, parsed_owner = parse_widget_token(widget_id)
        if not canonical:
            return {"recorded": False, "error": "widget_id is required"}
        owner_value = owner if owner is not None else parsed_owner
        purpose_value = normalize_purpose(purpose)
        identity = project_identity(project_root)
        record = {
            "widget_id": canonical,
            "owner": owner_value,
            "version": version or "unknown",
            "action": action,
            "purpose": purpose_value,
            "project_path": identity["project_path"],
            "project_remote": identity["project_remote"],
            "project_key": identity["project_key"],
            "used_at": _now_text(),
        }
        if previous_version:
            record["previous_version"] = previous_version
        _locked_append(record, carry_purpose=carry_purpose and not purpose_value)
        return {"recorded": True}
    except Exception as exc:
        return {"recorded": False, "error": str(exc)}


def installed_version(project_root: str, widget_id: str) -> str:
    """Read the installed widget version, or ``unknown``."""
    from .engine import DEFAULT_INSTALL_DIR, find_installed_widget_dir, python_dir_name
    root = os.path.abspath(project_root)
    direct = os.path.join(root, DEFAULT_INSTALL_DIR, python_dir_name(widget_id), "widget.json")
    path = direct
    if not os.path.isfile(path):
        found = find_installed_widget_dir(os.path.join(root, DEFAULT_INSTALL_DIR), widget_id)
        if not found:
            return "unknown"
        path = os.path.join(found, "widget.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return "unknown"
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict) and meta.get("version"):
        return str(meta["version"])
    if isinstance(data, dict) and data.get("version"):
        return str(data["version"])
    return "unknown"


def list_events(
    *,
    limit: int = 50,
    widget_id: str | None = None,
    project_only: bool = False,
    project_root: str = ".",
) -> dict:
    """Return recent events, newest first."""
    path = ledger_path()
    enabled = ledger_enabled()
    if limit < 0:
        return {"error": "limit must be >= 0"}
    loaded = _safe_read(path)
    if loaded is None:
        return {
            "status": "success",
            "path": path,
            "enabled": enabled,
            "count": 0,
            "skipped": 0,
            "events": [],
        }
    events = loaded["records"]
    if widget_id:
        events = [row for row in events if _same_widget(row, widget_id)]
    if project_only:
        key = project_identity(project_root)["project_key"]
        events = [row for row in events if row.get("project_key") == key]
    events = list(reversed(events))
    events = events[:limit]
    return {
        "status": "success",
        "path": path,
        "enabled": enabled,
        "count": len(events),
        "skipped": loaded["skipped"],
        "events": events,
    }


def forget_events(
    *,
    widget_id: str | None = None,
    project_only: bool = False,
    everything: bool = False,
    project_root: str = ".",
) -> dict:
    """Drop matching events. Works even when recording is turned off."""
    if not everything and not widget_id and not project_only:
        return {"error": "Pass --widget, --project, or --all."}
    path = ledger_path()
    if not os.path.isfile(path):
        return {"status": "success", "removed": 0, "kept": 0}
    project_key = project_identity(project_root)["project_key"] if project_only else ""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        from .safefs import path_lock
        with path_lock(path + ".lock", "usage ledger", timeout=LOCK_TIMEOUT_SECONDS):
            if everything:
                result = forget(path, everything=True)
                return {"status": "success", "removed": result["removed"], "kept": result["kept"]}
            if project_only:
                return _forget_project(path, project_key=project_key, widget_id=widget_id)
            loaded = read(path)
            ids = []
            seen = set()
            for row in loaded["records"]:
                stored = row.get("widget_id")
                if not isinstance(stored, str) or stored in seen:
                    continue
                if not widget_id or not _same_widget(row, widget_id):
                    continue
                seen.add(stored)
                ids.append(stored)
            removed = 0
            kept = len(loaded["records"])
            for stored in ids:
                result = forget(path, match={"widget_id": stored})
                removed += result["removed"]
                kept = result["kept"]
            return {"status": "success", "removed": removed, "kept": kept}
    except Exception as exc:
        return {"error": str(exc)}


def prior_for_search(
    query: str,
    *,
    project_root: str,
    library_versions: dict,
    registry_rows: list[dict],
    prefixes: list[str],
) -> dict | None:
    """Build the prior pool and per-id annotations.

    Returns None when the pool should be omitted (disabled, missing,
    unreadable, or no matches). Does not reorder caller-supplied rows.
    """
    if not ledger_enabled():
        return None
    path = ledger_path()
    if not os.path.isfile(path):
        return None
    loaded = _safe_read(path)
    if loaded is None:
        return None

    tokens = _TOKEN_RE.findall((query or "").lower())
    if not tokens:
        raw = (query or "").strip().lower()
        tokens = [raw] if len(raw) >= 2 else []
    if not tokens:
        return None

    latest: dict[str, dict] = {}
    for row in loaded["records"]:
        wid = row.get("widget_id")
        if isinstance(wid, str) and wid:
            latest[wid] = row

    hits = [row for row in latest.values() if _haystack_hit(row, tokens)]
    if not hits:
        return None

    project_key = project_identity(project_root)["project_key"]
    hits.sort(key=lambda row: row.get("used_at") or "", reverse=True)
    hits.sort(key=lambda row: 0 if row.get("project_key") == project_key else 1)

    flags = _registry_flags(registry_rows, prefixes)
    shown = hits[:PRIOR_LIMIT]
    omitted = len(hits) - len(shown)
    widgets = [
        _prior_row(row, project_key, library_versions, flags, prefixes)
        for row in shown
    ]
    annotations: dict[str, dict] = {}
    for row in hits:
        wid = str(row.get("widget_id") or "")
        prior = _prior_use(row, project_key)
        annotations[wid] = prior
        annotations[bare_id(wid, prefixes)] = prior
    return {
        "block": {"count": len(widgets), "omitted": omitted, "widgets": widgets},
        "annotations": annotations,
    }


def prior_use_for(widget_id: str, project_root: str | None = None) -> dict | None:
    """Return the latest prior_use object for ``widget_id``, or None."""
    if not widget_id or not ledger_enabled():
        return None
    path = ledger_path()
    if not os.path.isfile(path):
        return None
    loaded = _safe_read(path)
    if loaded is None:
        return None
    latest = None
    for row in loaded["records"]:
        if _same_widget(row, widget_id):
            latest = row
    if latest is None:
        return None
    root = project_root or os.getcwd()
    return _prior_use(latest, project_identity(root)["project_key"])


def version_status(used: str | None, library_version: str | None) -> str:
    """Compare a ledger version with the copy in the local library."""
    if not library_version:
        return "unknown"
    try:
        from cg.infra_version_bump_policy_python.src.version_bump_policy import (
            compare_versions,
        )
        cmp = compare_versions(used or "", library_version)
    except Exception:
        return "unknown"
    if cmp == 0:
        return "current"
    if cmp < 0:
        return "older"
    return "ahead"


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_origin(path: str) -> str | None:
    if not os.path.isdir(path):
        return None
    inside = _git(["rev-parse", "--is-inside-work-tree"], path)
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    # Stored config, not `remote get-url`. get-url applies url.insteadOf,
    # which can rewrite an SSH origin into an HTTPS URL that embeds a token.
    remote = _git(["config", "--get", "remote.origin.url"], path)
    if remote is None or remote.returncode != 0:
        return None
    url = remote.stdout.strip()
    return url or None


def _git(args: list[str], path: str):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _locked_append(record: dict, *, carry_purpose: bool) -> None:
    path = ledger_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    from .safefs import path_lock
    with path_lock(path + ".lock", "usage ledger", timeout=LOCK_TIMEOUT_SECONDS):
        if carry_purpose:
            found = _latest_purpose_unlocked(path, record["widget_id"], record["project_key"])
            if found:
                record["purpose"] = found
        append(path, record, max_records=MAX_RECORDS, max_line_bytes=MAX_LINE_BYTES)


def _latest_purpose_unlocked(path: str, widget_id: str, project_key: str) -> str | None:
    if not os.path.isfile(path):
        return None
    found = None
    for row in read(path)["records"]:
        if row.get("widget_id") != widget_id or row.get("project_key") != project_key:
            continue
        if row.get("purpose"):
            found = row["purpose"]
    return found


def _safe_read(path: str) -> dict | None:
    if not os.path.isfile(path):
        return {"records": [], "skipped": 0}
    try:
        return read(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _same_widget(row: dict, widget_id: str) -> bool:
    stored = row.get("widget_id")
    if not isinstance(stored, str) or not widget_id:
        return False
    canonical, _owner = parse_widget_token(widget_id)
    if stored == canonical:
        return True
    prefixes = _prefixes()
    return bare_id(stored, prefixes) == bare_id(canonical, prefixes) and bool(canonical)


def _prefixes() -> list[str]:
    try:
        from .config import _PUBLIC_REGISTRY_PREFIX, get_registries
        return [_PUBLIC_REGISTRY_PREFIX] + [item["prefix"] for item in get_registries()]
    except Exception:
        return ["cg"]


def _forget_project(path: str, *, project_key: str, widget_id: str | None) -> dict:
    """Drop rows for one project, optionally one widget, keeping every other row.

    Field equality cannot express "this project, except these widget ids"
    in one pass when several widget ids share the project, so this reads
    the file under the caller's lock and rewrites the keepers.
    """
    loaded = read(path)
    kept = []
    removed = 0
    for row in loaded["records"]:
        in_project = row.get("project_key") == project_key
        widget_ok = True if not widget_id else _same_widget(row, widget_id)
        if in_project and widget_ok:
            removed += 1
        else:
            kept.append(row)
    if removed:
        # Rewrite by clearing and appending keepers so the public widget
        # API stays the only writer. The caller holds the lock.
        forget(path, everything=True)
        for row in kept:
            append(path, row, max_records=MAX_RECORDS, max_line_bytes=MAX_LINE_BYTES)
    final = read(path)
    return {"status": "success", "removed": removed, "kept": len(final["records"])}


def _haystack_hit(row: dict, tokens: list[str]) -> bool:
    project_path = str(row.get("project_path") or "")
    hay = " ".join([
        str(row.get("widget_id") or ""),
        str(row.get("purpose") or ""),
        os.path.basename(project_path),
        str(row.get("project_remote") or ""),
    ]).lower()
    return any(token in hay for token in tokens)


def _registry_flags(rows: list[dict], prefixes: list[str]) -> dict:
    flags: dict[str, dict] = {}
    for row in rows:
        wid = str(row.get("id") or "")
        if not wid:
            continue
        key = bare_id(wid, prefixes)
        entry = flags.setdefault(key, {})
        if "deprecated" in row:
            entry["deprecated"] = bool(row["deprecated"])
        if "stale" in row:
            entry["stale"] = bool(row["stale"])
    return flags


def _prior_row(row: dict, project_key: str, library_versions: dict, flags: dict, prefixes: list[str]) -> dict:
    wid = str(row.get("widget_id") or "")
    bare = bare_id(wid, prefixes)
    library_version = library_versions.get(bare)
    if library_version is None:
        library_version = library_versions.get(wid)
    in_library = library_version is not None
    built = {
        "widget_id": wid,
        "version_used": row.get("version") or "unknown",
        "used_at": row.get("used_at"),
        "purpose": row.get("purpose"),
        "last_action": row.get("action"),
        "project_path": row.get("project_path"),
        "project_remote": row.get("project_remote"),
        "same_project": row.get("project_key") == project_key,
        "in_library": in_library,
        "library_version": library_version if in_library else None,
        "version_status": version_status(
            row.get("version") or "",
            library_version if in_library else None,
        ),
    }
    flag = flags.get(bare) or {}
    if "deprecated" in flag:
        built["deprecated"] = flag["deprecated"]
    if "stale" in flag:
        built["stale"] = flag["stale"]
    return built


def _prior_use(row: dict, project_key: str) -> dict:
    return {
        "version": row.get("version") or "unknown",
        "used_at": row.get("used_at"),
        "purpose": row.get("purpose"),
        "last_action": row.get("action"),
        "same_project": row.get("project_key") == project_key,
    }
