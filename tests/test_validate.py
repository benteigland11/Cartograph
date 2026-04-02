"""
Tests for validate_item — both passing and failing cases.
validate_item returns {"status": "error", "message": ...} on failure
and {"status": "passed", ...} on success.
"""
import os
import json
import pytest


def test_validate_valid_widget(carto, fixture_library):
    """A well-formed fixture widget should pass validation."""
    path = os.path.join(fixture_library, "http-client")
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


# ---------------------------------------------------------------------------
# Validation stamp invalidation on engine version bump
# ---------------------------------------------------------------------------

def test_stamp_invalidates_on_engine_version_bump(carto, fixture_library, tmp_path):
    """A stamp written with engine_version N should be stale if engine is now N+1."""
    import shutil
    from cartograph.languages.python import PythonEngine
    from cartograph.validation_stamp import write_stamp, is_stamp_valid

    # Copy fixture widget to a writable location
    widget_path = str(tmp_path / "http-client")
    shutil.copytree(os.path.join(fixture_library, "http-client"), widget_path)

    engine = PythonEngine()
    original_version = engine.validation_version

    # Write stamp at current version
    write_stamp(widget_path, "python", engine)
    assert is_stamp_valid(widget_path, "python", engine)

    # Simulate engine version bump
    engine.validation_version = original_version + 1
    assert not is_stamp_valid(widget_path, "python", engine)

    # Restore
    engine.validation_version = original_version
