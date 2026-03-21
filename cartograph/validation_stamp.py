"""
Validation stamp — short-circuit re-validation during checkin.

After a successful validate_item(), write_stamp() saves a fingerprint of all
watched files alongside the widget. checkin() calls is_stamp_valid() before
re-running validation; if the stamp is fresh the heavy pipeline is skipped.

Stamp is invalidated automatically when any watched file changes (content or
relative path), or when the recorded language differs from the widget manifest.

Which files are watched is language-specific: each LanguageEngine defines
watched_patterns(path) so that e.g. Rust can include Cargo.toml, Go can
include go.mod, etc. The base default covers all non-generated files under
src/, tests/, examples/, and widget.json.
"""

import glob
import hashlib
import importlib.metadata
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("cartograph")

STAMP_FILE = ".validation_stamp.json"

_SKIP_EXTENSIONS = frozenset({".pyc", ".pyo"})
_SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", "history", ".git"})


def _iter_watched_files(widget_path: str, engine) -> list[str]:
    """Return a sorted list of absolute paths for all watched files."""
    files = set()
    for pattern in engine.watched_patterns(widget_path):
        for f in glob.glob(pattern, recursive=True):
            if not os.path.isfile(f):
                continue
            rel_parts = os.path.relpath(f, widget_path).split(os.sep)
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            if os.path.splitext(f)[1] in _SKIP_EXTENSIONS:
                continue
            files.add(os.path.abspath(f))
    return sorted(files)


def _compute_fingerprint(widget_path: str, engine) -> str:
    """SHA-256 digest over (relative-path, content) of every watched file."""
    h = hashlib.sha256()
    for fpath in _iter_watched_files(widget_path, engine):
        rel = os.path.relpath(fpath, widget_path)
        h.update(rel.encode())
        try:
            with open(fpath, "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()


def _cartograph_version() -> str:
    try:
        return importlib.metadata.version("cartograph-cli")
    except Exception:
        return "dev"


def write_stamp(widget_path: str, language: str, engine,
                test_results: dict | None = None) -> None:
    """Write a fresh validation stamp.  Called after successful validate_item()."""
    stamp = {
        "language": language,
        "fingerprint": _compute_fingerprint(widget_path, engine),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "cartograph_version": _cartograph_version(),
        "test_results": test_results or {},
    }
    stamp_path = os.path.join(widget_path, STAMP_FILE)
    try:
        with open(stamp_path, "w") as f:
            json.dump(stamp, f)
        log.debug("Validation stamp written to %s", stamp_path)
    except OSError as e:
        log.debug("Could not write validation stamp: %s", e)


def read_stamp(widget_path: str) -> dict | None:
    """Return the stamp dict if it exists, else None."""
    stamp_path = os.path.join(widget_path, STAMP_FILE)
    try:
        with open(stamp_path) as f:
            return json.load(f)
    except Exception:
        return None


def is_stamp_valid(widget_path: str, language: str, engine) -> bool:
    """Return True if the stamp exists, language matches, and no watched file changed."""
    stamp_path = os.path.join(widget_path, STAMP_FILE)
    if not os.path.exists(stamp_path):
        return False
    try:
        with open(stamp_path) as f:
            stamp = json.load(f)
    except Exception:
        return False
    if stamp.get("language") != language:
        return False
    current = _compute_fingerprint(widget_path, engine)
    valid = stamp.get("fingerprint") == current
    if not valid:
        log.debug("Validation stamp is stale (files changed)")
    return valid
