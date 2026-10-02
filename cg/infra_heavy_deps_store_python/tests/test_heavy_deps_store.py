import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.heavy_deps_store import (
    StoreRoot,
    dependency_dir,
    installed_versions,
    resolve_root,
    version_dir,
)


def test_first_non_blank_layer_wins(tmp_path):
    root = resolve_root([("env", None), ("config", str(tmp_path / "a")),
                         ("other", str(tmp_path / "b"))],
                        default=tmp_path / "d")
    assert root == StoreRoot(tmp_path / "a", "config")


def test_blank_layers_fall_through_to_default(tmp_path):
    root = resolve_root([("env", ""), ("config", "   ")],
                        default=str(tmp_path / "d"), default_label="data dir")
    assert root.path == tmp_path / "d"
    assert root.source == "data dir"


def test_no_layers_uses_default(tmp_path):
    assert resolve_root([], default=tmp_path).source == "default"


def test_value_is_stripped_expanded_and_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = resolve_root([("env", "  ~/store  ")], default="/unused")
    assert root.path == Path(os.path.abspath(tmp_path / "store"))
    rel = resolve_root([("env", "relative/store")], default="/unused")
    assert rel.path.is_absolute()


def test_layout(tmp_path):
    assert dependency_dir(tmp_path, "item") == tmp_path / "item"
    assert version_dir(tmp_path, "item", "v1.2.0") == \
        tmp_path / "item" / "v1.2.0"


@pytest.mark.parametrize("bad", ["", "..", ".", "a/b", "a\\b", " v1"])
def test_rejects_non_segment_version(tmp_path, bad):
    with pytest.raises(ValueError, match="version"):
        version_dir(tmp_path, "item", bad)


def test_rejects_non_segment_name(tmp_path):
    with pytest.raises(ValueError, match="dependency name"):
        dependency_dir(tmp_path, "../escape")


def test_installed_versions_empty_when_missing(tmp_path):
    assert installed_versions(tmp_path, "item") == []


def test_installed_versions_lists_and_filters(tmp_path):
    base = tmp_path / "item"
    for v in ("v2", "v1", ".lock-dir", "v3"):
        (base / v).mkdir(parents=True)
    (base / "stray.txt").write_text("x", encoding="utf-8")
    (base / "v1" / "done.json").write_text("{}", encoding="utf-8")
    (base / "v3" / "done.json").write_text("{}", encoding="utf-8")
    assert installed_versions(tmp_path, "item") == ["v1", "v2", "v3"]
    assert installed_versions(tmp_path, "item",
                              marker="done.json") == ["v1", "v3"]
