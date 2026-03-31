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

import importlib.metadata
import logging

from cg.infra_file_stamp_python.src.file_stamp import (
    collect_files as _collect_files,
    fingerprint as _fingerprint,
    write_stamp as _write_stamp,
    read_stamp,
    is_stamp_valid as _is_stamp_valid,
)

log = logging.getLogger("cartograph")

STAMP_FILE = ".validation_stamp.json"


def _cartograph_version() -> str:
    try:
        return importlib.metadata.version("cartograph-cli")
    except Exception:
        return "dev"


def _engine_patterns(widget_path: str, engine) -> list[str]:
    """Get watched file patterns from a language engine."""
    return list(engine.watched_patterns(widget_path))


def write_stamp(widget_path: str, language: str, engine,
                test_results: dict | None = None) -> None:
    """Write a fresh validation stamp. Called after successful validate_item()."""
    patterns = _engine_patterns(widget_path, engine)
    metadata = {
        "language": language,
        "cartograph_version": _cartograph_version(),
        "test_results": test_results or {},
    }
    try:
        _write_stamp(widget_path, metadata=metadata, stamp_name=STAMP_FILE,
                     patterns=patterns)
        log.debug("Validation stamp written to %s", widget_path)
    except OSError as e:
        log.debug("Could not write validation stamp: %s", e)


def is_stamp_valid(widget_path: str, language: str, engine) -> bool:
    """Return True if the stamp exists, language matches, and no watched file changed."""
    patterns = _engine_patterns(widget_path, engine)
    valid = _is_stamp_valid(
        widget_path,
        metadata_match={"language": language},
        stamp_name=STAMP_FILE,
        patterns=patterns,
    )
    if not valid:
        log.debug("Validation stamp is stale or missing")
    return valid
