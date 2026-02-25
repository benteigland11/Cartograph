"""
Tests for validate_item — both passing and failing cases.
validate_item returns {"status": "error", "message": ...} on failure
and {"status": "passed", ...} on success.
"""
import os
import json
import pytest


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
WIDGET_LIBRARY = os.path.join(FIXTURES_DIR, "Widget_Library")


def test_validate_valid_widget(carto):
    """A well-formed fixture widget should pass validation."""
    path = os.path.join(WIDGET_LIBRARY, "http-client")
    result = carto.validate_item(path)
    assert isinstance(result, dict)
    assert result.get("status") != "error", f"Unexpected error: {result.get('message')}"


def test_validate_missing_path(carto):
    """Validating a non-existent path should return status=error."""
    result = carto.validate_item("/tmp/totally-fake-widget-xyz")
    assert result.get("status") == "error"


def test_validate_missing_manifest(carto, tmp_path):
    """A widget dir with no widget.json should return status=error."""
    widget_dir = tmp_path / "bad-widget"
    widget_dir.mkdir()
    result = carto.validate_item(str(widget_dir))
    assert result.get("status") == "error"


def test_validate_minimal_widget(carto, tmp_path):
    """A widget with a manifest but no src/ should return status=error."""
    widget_dir = tmp_path / "minimal-widget"
    widget_dir.mkdir()
    manifest = {
        "meta": {"id": "minimal-widget", "name": "Minimal Widget",
                 "version": "1.0.0", "tags": ["test"], "domain": "backend"},
        "description": "A minimal widget for testing.",
        "tech_stack": {"language": "python", "dependencies": []},
    }
    (widget_dir / "widget.json").write_text(json.dumps(manifest))
    result = carto.validate_item(str(widget_dir))
    assert isinstance(result, dict)
    assert result.get("status") == "error"


def test_validate_invalid_domain(carto, tmp_path):
    widget_dir = tmp_path / "bad-domain"
    widget_dir.mkdir()
    manifest = {
        "meta": {"id": "bad-domain", "name": "Bad Domain", "domain": "enterprise"},
        "description": "Test.",
        "tech_stack": {"language": "python", "dependencies": []},
    }
    (widget_dir / "widget.json").write_text(json.dumps(manifest))
    result = carto.validate_item(str(widget_dir))
    assert result.get("status") == "error"
    assert "domain" in result.get("message", "").lower()
