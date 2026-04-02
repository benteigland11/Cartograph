"""
Tests for the checkin workflow: install → edit → push back to library.

Each test that modifies the library fixture uses a fresh tmp_path copy
so the session-scoped carto fixture is not polluted.
"""
import json
import os
import shutil
from unittest.mock import patch
import pytest


@pytest.fixture
def tmp_library(fixture_library, tmp_path):
    """A writable copy of the fixture Widget_Library."""
    dst = tmp_path / "Widget_Library"
    shutil.copytree(fixture_library, dst)
    return str(dst)


@pytest.fixture
def carto_tmp(tmp_library):
    """A Cartograph instance pointed at the writable library copy."""
    from cartograph import Cartograph
    return Cartograph(library_path=tmp_library)


@pytest.fixture
def installed_widget(carto_tmp, tmp_path):
    """Install http-client into tmp_path and return the installed dir."""
    install_dir = str(tmp_path / "myproject")
    result = carto_tmp.install("http-client", target_dir=install_dir)
    if result.get("status") != "success":
        pytest.fail(f"Fixture setup: install failed - {result}")
    return result["installed_at"]


# ---------------------------------------------------------------------------
# Basic checkin
# ---------------------------------------------------------------------------

def test_checkin_clean_widget(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Added retry logic")
    assert result["status"] == "success"
    assert result["action"] == "updated"
    assert result["version"] > "1.2.0"   # bumped from fixture version


def test_checkin_bumps_version_minor(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Minor fix", version_bump="minor")
    assert result["status"] == "success"
    # 1.2.0 → 1.3.0
    assert result["version"] == "1.3.0"


def test_checkin_bumps_version_patch(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Patch", version_bump="patch")
    assert result["version"] == "1.2.1"


def test_checkin_bumps_version_major(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Breaking change", version_bump="major")
    assert result["version"] == "2.0.0"


def test_checkin_leaves_source_intact(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Test")
    assert result["status"] == "success", f"Checkin failed: {result}"
    assert os.path.isdir(installed_widget), "Source dir must be left in place after checkin"
    assert os.path.exists(os.path.join(installed_widget, "widget.json"))


def test_checkin_archives_old_version(carto_tmp, installed_widget):
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    old_version = widget["version"]
    carto_tmp.checkin(installed_widget, reason="Update")
    history = os.path.join(widget["path"], "history", old_version)
    assert os.path.isdir(history), f"Expected history archive at {history}"


def test_checkin_writes_changelog(carto_tmp, installed_widget):
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    carto_tmp.checkin(installed_widget, reason="Fixed timeout")
    changelog_path = os.path.join(widget["path"], "changelog.json")
    assert os.path.exists(changelog_path)
    with open(changelog_path) as f:
        log = json.load(f)
    assert log[0]["reason"] == "Fixed timeout"


def test_checkin_missing_path_errors(carto_tmp):
    result = carto_tmp.checkin("/nonexistent/path", reason="Test")
    assert result["status"] == "error"


def test_checkin_no_widget_json_errors(carto_tmp, tmp_path):
    empty = str(tmp_path / "empty")
    os.makedirs(empty)
    result = carto_tmp.checkin(empty, reason="Test")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Contamination: hard blocks
# ---------------------------------------------------------------------------

def test_checkin_blocks_absolute_path(carto_tmp, installed_widget):
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\nLOG_DIR = "/home/user/logs/myapp"\n')
    result = carto_tmp.checkin(installed_widget, reason="Test")
    assert result["status"] == "error"
    assert "blocks" in result
    assert any("Absolute path" in b for b in result["blocks"])


def test_checkin_blocks_credential(carto_tmp, installed_widget):
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\napi_key = "sk-abc123verylongkey"\n')
    result = carto_tmp.checkin(installed_widget, reason="Test")
    assert result["status"] == "error"
    assert any("credential" in b.lower() for b in result["blocks"])


# ---------------------------------------------------------------------------
# Contamination: warnings + override
# ---------------------------------------------------------------------------

def _add_getenv(installed_widget):
    """Append a valid os.getenv call to the main src file."""
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py") and not f.startswith("__")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\nimport os\n_TIMEOUT = int(os.getenv("TIMEOUT", "30"))\n')


def test_checkin_warns_on_os_getenv(carto_tmp, installed_widget):
    _add_getenv(installed_widget)
    result = carto_tmp.checkin(installed_widget, reason="Test")
    assert result["status"] == "warnings"
    assert any("getenv" in w for w in result["warnings"])


def test_checkin_override_warnings_requires_reason(carto_tmp, installed_widget):
    _add_getenv(installed_widget)
    result = carto_tmp.checkin(installed_widget, reason="Test",
                               override_warnings=True, override_reason="")
    assert result["status"] == "error"


def test_checkin_override_warnings_with_reason_succeeds(carto_tmp, installed_widget):
    _add_getenv(installed_widget)
    result = carto_tmp.checkin(
        installed_widget, reason="Configurable timeout",
        override_warnings=True,
        override_reason="os.getenv used for optional timeout, not project-specific",
    )
    assert result["status"] == "success"
    assert "override_reason" in result


def test_checkin_override_reason_in_changelog(carto_tmp, installed_widget):
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    _add_getenv(installed_widget)
    carto_tmp.checkin(
        installed_widget, reason="Configurable timeout",
        override_warnings=True,
        override_reason="optional env var, safe",
    )
    with open(os.path.join(widget["path"], "changelog.json")) as f:
        log = json.load(f)
    assert log[0].get("override_reason") == "optional env var, safe"


# ---------------------------------------------------------------------------
# library_notes stamped at create and restored on checkin
# ---------------------------------------------------------------------------

def test_create_stamps_library_notes(carto_tmp, tmp_path):
    target = str(tmp_path)
    result = carto_tmp.create("new-widget", language="python", name="New Widget",
                               domain="backend", tags=[], target_dir=target)
    assert result["status"] == "success"
    with open(os.path.join(result["path"], "widget.json")) as f:
        data = json.load(f)
    notes = data.get("library_notes", {})
    assert notes.get("general"), "general notes should be stamped"
    assert notes.get("language"), "language notes should be stamped"
    assert "pytest" in notes["language"]


def test_checkin_restores_library_notes_if_edited(carto_tmp, installed_widget):
    # Agent tampers with library_notes in the installed copy
    manifest_path = os.path.join(installed_widget, "widget.json")
    with open(manifest_path) as f:
        data = json.load(f)
    data["library_notes"] = {"general": "do whatever", "language": "anything goes"}
    with open(manifest_path, "w") as f:
        json.dump(data, f)

    carto_tmp.checkin(installed_widget, reason="Tampered notes test")

    # Library copy should have canonical notes, not the tampered ones
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "widget.json")) as f:
        lib_data = json.load(f)
    notes = lib_data.get("library_notes", {})
    assert notes.get("general") != "do whatever"
    assert "pytest" in notes.get("language", "")


def test_checkin_fails_if_library_notes_restore_fails(carto_tmp, installed_widget):
    with patch("cartograph.checkin._canonical_library_notes", side_effect=RuntimeError("boom")):
        result = carto_tmp.checkin(installed_widget, reason="library notes strictness")
    assert result["status"] == "error"
    assert "boom" in result["message"].lower() or "invalid" in result["message"].lower()


# ---------------------------------------------------------------------------
# Validation version stamped into widget.json
# ---------------------------------------------------------------------------

def test_checkin_stamps_validation_block(carto_tmp, installed_widget):
    result = carto_tmp.checkin(installed_widget, reason="Version stamp test")
    assert result["status"] == "success"

    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "widget.json")) as f:
        data = json.load(f)

    assert "validation" in data
    v = data["validation"]
    assert "engine_version" in v
    assert "cartograph_version" in v
    assert "validated_at" in v
    assert isinstance(v["engine_version"], int)
    assert v["engine_version"] >= 1


def test_checkin_stamps_correct_engine_version(carto_tmp, installed_widget):
    from cartograph.languages.python import PythonEngine
    result = carto_tmp.checkin(installed_widget, reason="Engine version check")
    assert result["status"] == "success"

    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "widget.json")) as f:
        data = json.load(f)

    assert data["validation"]["engine_version"] == PythonEngine.validation_version


def test_checkin_stamps_runtime_version(carto_tmp, installed_widget):
    import sys
    result = carto_tmp.checkin(installed_widget, reason="Runtime stamp test")
    assert result["status"] == "success"

    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "widget.json")) as f:
        data = json.load(f)

    v = data["validation"]
    assert "runtime" in v
    assert v["runtime"].startswith("python ")
    # Should match the running interpreter
    expected = f"python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert v["runtime"] == expected


# ---------------------------------------------------------------------------
# Rollback (restore)
# ---------------------------------------------------------------------------

def test_rollback_restores_old_version(carto_tmp, installed_widget):
    """Rollback should restore a previous version's source as a new patch release."""
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    old_version = widget["version"]

    # Checkin to create a history entry
    src_file = os.path.join(installed_widget, "src", "http_client.py")
    with open(src_file, "a") as f:
        f.write("\n# v2 change\n")
    result = carto_tmp.checkin(installed_widget, reason="v2 change")
    assert result["status"] == "success"
    new_version = result["version"]

    # Rollback to old version
    from cartograph.checkin import restore
    result = restore(carto_tmp, "http-client", old_version, "reverting v2")
    assert result["status"] == "success"
    assert result["action"] == "updated"
    # Restore does a patch bump from the current library version (1.3.0 -> 1.3.1)
    assert result["version"] == "1.3.1"

    # Source should NOT contain the v2 change
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "src", "http_client.py")) as f:
        content = f.read()
    assert "# v2 change" not in content


def test_rollback_records_reason_in_changelog(carto_tmp, installed_widget):
    """Rollback reason should appear in the changelog."""
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    old_version = widget["version"]

    carto_tmp.checkin(installed_widget, reason="setup")

    from cartograph.checkin import restore
    restore(carto_tmp, "http-client", old_version, "broke prod")

    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    with open(os.path.join(widget["path"], "changelog.json")) as f:
        log = json.load(f)
    assert any("RESTORE" in entry["reason"] and "broke prod" in entry["reason"]
               for entry in log)


def test_rollback_unknown_widget_errors(carto_tmp):
    from cartograph.checkin import restore
    result = restore(carto_tmp, "nonexistent-widget", "1.0.0", "test")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


def test_rollback_unknown_version_errors(carto_tmp, installed_widget):
    from cartograph.checkin import restore
    result = restore(carto_tmp, "http-client", "99.99.99", "test")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()
