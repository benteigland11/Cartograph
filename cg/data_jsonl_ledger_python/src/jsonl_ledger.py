"""Append-only JSONL ledger.

One JSON object per line in a caller-supplied file. ``append`` writes a
single UTF-8 line and fsyncs it. ``read`` returns the objects and counts
lines that are not JSON objects. ``forget`` drops matching objects, or
every object, by rewriting through a sibling temp file and ``os.replace``.

This module does not lock. Callers that share a file across processes
must serialize ``append`` and ``forget`` themselves. A reader that meets
a torn last line counts that line as skipped.
"""

from __future__ import annotations

import json
import os
import tempfile


def append(
    path: str,
    record: dict,
    *,
    max_records: int | None = None,
    max_line_bytes: int | None = None,
) -> dict:
    """Append ``record`` as one JSON line.

    ``max_records``, when set, keeps the newest valid objects after the
    append (older objects, and any corrupt lines, are dropped by the
    rewrite). ``max_line_bytes``, when set, refuses a line longer than
    that many UTF-8 bytes, including the trailing newline. The file is
    created with mode 0o600. The parent directory must already exist.

    Returns ``{"status": "ok", "records": <count>}``.
    """
    _require_path(path)
    if not isinstance(record, dict):
        raise TypeError("record must be a JSON object")
    _check_max_records(max_records)
    _check_max_line_bytes(max_line_bytes)

    line = _dump_line(record)
    encoded = line.encode("utf-8")
    if max_line_bytes is not None and len(encoded) > max_line_bytes:
        raise ValueError("record exceeds max_line_bytes")

    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        raise FileNotFoundError(f"directory does not exist: {parent}")

    _append_line(path, encoded)
    loaded = read(path)
    records = loaded["records"]
    if max_records is not None and len(records) > max_records:
        # records[-0:] is the whole list because -0 == 0, so a zero cap
        # has to be spelled out.
        records = records[-max_records:] if max_records else []
        _rewrite(path, records)
    return {"status": "ok", "records": len(records)}


def read(path: str) -> dict:
    """Return ``{"records": [...], "skipped": n}``.

    A missing file is an empty ledger. Blank lines are ignored. Any other
    line that is not a JSON object increments ``skipped`` and is left out
    of ``records``.
    """
    _require_path(path)
    if not os.path.exists(path):
        return {"records": [], "skipped": 0}

    records: list[dict] = []
    skipped = 0
    with open(path, "r", encoding="utf-8", newline="\n") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(value, dict):
                records.append(value)
            else:
                skipped += 1
    return {"records": records, "skipped": skipped}


def forget(
    path: str,
    *,
    match: dict | None = None,
    everything: bool = False,
) -> dict:
    """Drop records and return ``{"removed": n, "kept": n}``.

    ``everything=True`` clears the file. Otherwise ``match`` must be a
    non-empty object, and a record is removed when every match field is
    present and equal. A missing file removes nothing and is not created.
    """
    _require_path(path)
    if not everything:
        if match is None or match == {}:
            raise ValueError(
                "forget requires match with at least one field, or everything=True"
            )
        if not isinstance(match, dict):
            raise TypeError("match must be a JSON object")
    if not os.path.exists(path):
        return {"removed": 0, "kept": 0}

    records = read(path)["records"]
    if everything:
        _rewrite(path, [])
        return {"removed": len(records), "kept": 0}

    kept: list[dict] = []
    removed = 0
    for record in records:
        if _matches(record, match or {}):
            removed += 1
        else:
            kept.append(record)
    if removed:
        _rewrite(path, kept)
    return {"removed": removed, "kept": len(kept)}


def _require_path(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise TypeError("path must be a non-empty string")


def _check_max_records(max_records: int | None) -> None:
    if max_records is None:
        return
    if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 0:
        raise ValueError("max_records must be a non-negative integer or None")


def _check_max_line_bytes(max_line_bytes: int | None) -> None:
    if max_line_bytes is None:
        return
    if (
        isinstance(max_line_bytes, bool)
        or not isinstance(max_line_bytes, int)
        or max_line_bytes < 1
    ):
        raise ValueError("max_line_bytes must be a positive integer or None")


def _dump_line(record: dict) -> str:
    return json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"


def _matches(record: dict, match: dict) -> bool:
    for key, expected in match.items():
        if key not in record or record[key] != expected:
            return False
    return True


def _append_line(path: str, encoded: bytes) -> None:
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)


def _rewrite(path: str, records: list[dict]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        raise FileNotFoundError(f"directory does not exist: {parent}")

    _fd, tmp_name = tempfile.mkstemp(prefix=".ledger-", suffix=".tmp", dir=parent or None)
    try:
        with os.fdopen(_fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(_dump_line(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = ""
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
