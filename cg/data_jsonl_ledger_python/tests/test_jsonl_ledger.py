"""Tests for the append-only JSONL ledger."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.jsonl_ledger import append, forget, read  # noqa: E402


def _path(tmp_path, name="events.jsonl"):
    return str(tmp_path / name)


def test_append_and_read_roundtrip(tmp_path):
    path = _path(tmp_path)
    first = append(path, {"item": "alpha", "n": 1})
    second = append(path, {"item": "beta", "n": 2})
    loaded = read(path)
    assert first == {"status": "ok", "records": 1}
    assert second["records"] == 2
    assert loaded == {
        "records": [{"item": "alpha", "n": 1}, {"item": "beta", "n": 2}],
        "skipped": 0,
    }


def test_utf8_roundtrip(tmp_path):
    path = _path(tmp_path)
    append(path, {"note": "caf\u00e9"})
    assert read(path)["records"] == [{"note": "caf\u00e9"}]
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    assert "caf\u00e9" in raw


def test_skips_corrupt_lines(tmp_path):
    path = _path(tmp_path)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"item": "alpha"}\n')
        handle.write("\n")
        handle.write("NOT JSON\n")
        handle.write("[1, 2]\n")
        handle.write('{"item": "beta"}\n')
    loaded = read(path)
    assert loaded["records"] == [{"item": "alpha"}, {"item": "beta"}]
    assert loaded["skipped"] == 2


def test_read_missing_file(tmp_path):
    assert read(_path(tmp_path, "missing.jsonl")) == {"records": [], "skipped": 0}


def test_forget_matches_all_fields(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "alpha", "note": "one"})
    append(path, {"item": "alpha", "note": "two"})
    append(path, {"item": "beta", "note": "one"})

    missed = forget(path, match={"item": "alpha", "note": "missing"})
    assert missed == {"removed": 0, "kept": 3}
    assert read(path)["skipped"] == 0

    dropped = forget(path, match={"item": "alpha", "note": "one"})
    assert dropped == {"removed": 1, "kept": 2}
    left = [row["note"] for row in read(path)["records"]]
    assert left == ["two", "one"]

    partial = forget(path, match={"item": "alpha"})
    assert partial == {"removed": 1, "kept": 1}
    assert read(path)["records"] == [{"item": "beta", "note": "one"}]


def test_forget_keeps_corrupt_line_when_nothing_matches(tmp_path):
    path = _path(tmp_path)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"item": "alpha"}\n')
        handle.write("NOT JSON\n")
    result = forget(path, match={"item": "missing"})
    assert result == {"removed": 0, "kept": 1}
    assert read(path)["skipped"] == 1


def test_forget_all(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "alpha"})
    append(path, {"item": "beta"})
    cleared = forget(path, everything=True)
    assert cleared == {"removed": 2, "kept": 0}
    assert read(path) == {"records": [], "skipped": 0}


def test_forget_everything_wins_over_match(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "alpha"})
    append(path, {"item": "beta"})
    cleared = forget(path, match={"item": "alpha"}, everything=True)
    assert cleared == {"removed": 2, "kept": 0}


def test_forget_without_selector_raises(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "alpha"})
    with pytest.raises(ValueError):
        forget(path)
    with pytest.raises(ValueError):
        forget(path, match={})
    with pytest.raises(TypeError):
        forget(path, match=["item"])
    assert read(path)["records"] == [{"item": "alpha"}]


def test_forget_missing_file(tmp_path):
    missing = _path(tmp_path, "missing.jsonl")
    assert forget(missing, everything=True) == {"removed": 0, "kept": 0}
    assert forget(missing, match={"item": "alpha"}) == {"removed": 0, "kept": 0}
    assert not os.path.exists(missing)


def test_max_records_drops_oldest(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "a"})
    append(path, {"item": "b"})
    result = append(path, {"item": "c"}, max_records=2)
    assert result == {"status": "ok", "records": 2}
    assert [row["item"] for row in read(path)["records"]] == ["b", "c"]


def test_max_records_zero_keeps_nothing(tmp_path):
    path = _path(tmp_path)
    result = append(path, {"item": "a"}, max_records=0)
    assert result == {"status": "ok", "records": 0}
    assert read(path)["records"] == []


def test_max_records_drops_corrupt_lines_on_rewrite(tmp_path):
    path = _path(tmp_path)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"item": "a"}\n')
        handle.write("NOT JSON\n")
    append(path, {"item": "b"}, max_records=1)
    loaded = read(path)
    assert loaded["records"] == [{"item": "b"}]
    assert loaded["skipped"] == 0


def test_rejects_non_object_and_overlong_line(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "kept"})
    with pytest.raises(TypeError):
        append(path, ["nope"])
    with pytest.raises(TypeError):
        append(path, "nope")
    with pytest.raises(ValueError):
        append(path, {"n": float("nan")})
    with pytest.raises(ValueError):
        append(path, {"note": "x" * 40}, max_line_bytes=16)
    with pytest.raises(ValueError):
        append(path, {"item": "z"}, max_records=-1)
    with pytest.raises(ValueError):
        append(path, {"item": "z"}, max_records=True)
    with pytest.raises(ValueError):
        append(path, {"item": "z"}, max_line_bytes=0)
    with pytest.raises(TypeError):
        append("", {"item": "z"})
    with pytest.raises(TypeError):
        append(None, {"item": "z"})
    assert read(path)["records"] == [{"item": "kept"}]


def test_missing_parent_directory(tmp_path):
    missing = str(tmp_path / "missing" / "events.jsonl")
    with pytest.raises(FileNotFoundError):
        append(missing, {"item": "a"})


def test_read_rejects_bad_utf8_and_directory(tmp_path):
    path = _path(tmp_path)
    with open(path, "wb") as handle:
        handle.write(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        read(path)
    with pytest.raises(OSError):
        read(str(tmp_path))


def test_file_mode_0600(tmp_path):
    path = _path(tmp_path)
    append(path, {"item": "alpha"})
    if os.name == "nt":
        assert os.path.isfile(path)
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
    forget(path, everything=True)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_rewrite_cleans_temp_and_keeps_original(tmp_path, monkeypatch):
    path = _path(tmp_path)
    append(path, {"item": "alpha"})

    def boom(*_args, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        forget(path, everything=True)
    assert read(path)["records"] == [{"item": "alpha"}]
    leftovers = [name for name in os.listdir(tmp_path) if name.startswith(".ledger-")]
    assert leftovers == []


def test_roundtrip_preserves_nested_values(tmp_path):
    path = _path(tmp_path)
    record = {"item": "alpha", "flag": True, "empty": None, "nested": {"k": [1, "two"]}}
    append(path, record)
    assert read(path)["records"] == [record]
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw == record
