"""
Tests for widget scaffolding via create().
create() returns {"status": "success", "path": ..., "item_id": ...}
or {"status": "error", "message": ...}
"""
import os
import json
import pytest


@pytest.fixture
def carto_with_tempdir(carto, tmp_path):
    return carto, tmp_path


def _assert_scaffold(widget_dir, expected_paths):
    for rel_path in expected_paths:
        full = os.path.join(widget_dir, rel_path)
        assert os.path.exists(full), f"Expected scaffold path missing: {rel_path}"


def test_create_python_widget(carto_with_tempdir):
    carto, tmp_path = carto_with_tempdir
    target = str(tmp_path)
    result = carto.create(
        "my-widget",
        language="python",
        name="My Widget",
        domain="backend",
        tags=["test"],
        target_dir=target,
    )
    assert result.get("status") == "success"
    widget_dir = result["path"]
    _assert_scaffold(widget_dir, ["widget.json", "src", "tests", "examples"])


def test_create_javascript_widget(carto_with_tempdir):
    carto, tmp_path = carto_with_tempdir
    target = str(tmp_path)
    result = carto.create(
        "my-js-widget",
        language="javascript",
        name="My JS Widget",
        domain="frontend",
        tags=["ui"],
        target_dir=target,
    )
    assert result.get("status") == "success"
    widget_dir = result["path"]
    _assert_scaffold(widget_dir, ["widget.json", "src", "tests"])


def test_create_widget_manifest_valid(carto_with_tempdir):
    carto, tmp_path = carto_with_tempdir
    target = str(tmp_path)
    result = carto.create(
        "manifest-widget",
        language="python",
        name="Manifest Widget",
        domain="backend",
        tags=["manifest", "test"],
        target_dir=target,
    )
    assert result.get("status") == "success"
    widget_dir = result["path"]
    manifest_path = os.path.join(widget_dir, "widget.json")
    assert os.path.exists(manifest_path)
    with open(manifest_path) as f:
        data = json.load(f)
    meta = data.get("meta", data)
    # create() appends the language to the id (e.g. "manifest-widget-python")
    assert "manifest-widget" in meta.get("id", "")
    assert "tags" in meta


def test_create_duplicate_widget_errors(carto_with_tempdir):
    carto, tmp_path = carto_with_tempdir
    target = str(tmp_path)
    carto.create("dupe-widget", language="python", name="Dupe", domain="backend", tags=[], target_dir=target)
    result = carto.create("dupe-widget", language="python", name="Dupe", domain="backend", tags=[], target_dir=target)
    assert result.get("status") == "error"
