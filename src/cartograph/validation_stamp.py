"""
Validation stamp - short-circuit re-validation during checkin.

After a successful validate_item(), write_stamp() saves a fingerprint of all
watched files alongside the widget. checkin() calls is_stamp_valid() before
re-running validation; if the stamp is fresh the heavy pipeline is skipped.

Stamp is invalidated automatically when any watched file changes (content or
relative path), or when the recorded language differs from the widget manifest.

Delegates to the infra-file-stamp-python widget for fingerprinting and stamp
I/O. This module adds Cartograph-specific concerns: language engines for
watched_patterns, cartograph version tracking, and test result storage.
"""

import logging

from cg.infra_file_stamp_python.src.file_stamp import (
    write_stamp as _write_stamp,
    read_stamp as _read_stamp,
    is_stamp_valid as _is_stamp_valid,
)

log = logging.getLogger("cartograph")

STAMP_FILE = ".validation_stamp.json"



def write_stamp(widget_path: str, language: str, engine,
                test_results: dict | None = None) -> None:
    """Write a fresh validation stamp. Called after successful validate_item()."""
    patterns = engine.watched_patterns(widget_path)
    from datetime import datetime, timezone
    rv = engine.runtime_version() if engine else None
    metadata = {
        "language": language,
        "engine_version": getattr(engine, "validation_version", None),
        "runtime": rv,
        "test_results": test_results or {},
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_stamp(widget_path, metadata=metadata, stamp_name=STAMP_FILE,
                 patterns=patterns)
    log.debug("Validation stamp written to %s", widget_path)


def read_stamp(widget_path: str) -> dict | None:
    """Read the validation stamp if it exists, else None."""
    return _read_stamp(widget_path, stamp_name=STAMP_FILE)


def is_stamp_valid(widget_path: str, language: str, engine) -> bool:
    """Return True if the stamp exists, language matches, and no watched file changed."""
    patterns = engine.watched_patterns(widget_path)
    valid = _is_stamp_valid(
        widget_path,
        metadata_match={
            "language": language,
            "engine_version": getattr(engine, "validation_version", None),
        },
        stamp_name=STAMP_FILE,
        patterns=patterns,
    )
    if not valid:
        log.debug("Validation stamp is stale or missing")
    return valid


def has_valid_stamp(widget_path: str, language: str) -> bool:
    """Lightweight scan-time check: does this widget carry a stamp whose
    fingerprint still matches its files?

    Used by the library-integrity gate (Day 40). Unlike is_stamp_valid(),
    this does NOT match on engine_version or language — a stale stamp still
    proves the widget was run through `cartograph checkin` at some point,
    which is what we care about here. A widget that was never checked in
    (attacker drops files into Widget_Library/) has no stamp at all and
    fails this check.

    Returns False on any error (missing engine, unreadable files, etc.)
    so unresolvable widgets stay out of the index.
    """
    try:
        from .languages import get_engine
        engine = get_engine(language)
        if engine is None:
            return False
        patterns = engine.watched_patterns(widget_path)
    except Exception:
        return False
    return _is_stamp_valid(
        widget_path,
        metadata_match=None,
        stamp_name=STAMP_FILE,
        patterns=patterns,
    )
