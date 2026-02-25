"""
Tests for the checkin workflow: install → edit → push back to library.

Each test that modifies the library fixture uses a fresh tmp_path copy
so the session-scoped carto fixture is not polluted.
"""
import json
import os
import shutil
import pytest


@pytest.fixture
def tmp_library(tmp_path):
    """A writable copy of the fixture Widget_Library."""
    src = os.path.join(os.path.dirname(__file__), "fixtures", "Widget_Library")
    dst = tmp_path / "Widget_Library"
    shutil.copytree(src, dst)
    return str(dst)


@pytest.fixture
def carto_tmp(tmp_library):
    """A Cartographer instance pointed at the writable library copy."""
    from cartographer import Cartographer
    return Cartographer(library_path=tmp_library)


@pytest.fixture
def installed_widget(carto_tmp, tmp_path):
    """Install http-client into tmp_path and return the installed dir."""
    install_dir = str(tmp_path / "myproject")
    result = carto_tmp.install("http-client", target_dir=install_dir)
    assert result["status"] == "success", result
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
    carto_tmp.checkin(installed_widget, reason="Test")
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

def test_checkin_warns_on_os_getenv(carto_tmp, installed_widget):
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\ntimeout = int(os.getenv("TIMEOUT", "30"))\n')
    result = carto_tmp.checkin(installed_widget, reason="Test")
    assert result["status"] == "warnings"
    assert any("getenv" in w for w in result["warnings"])


def test_checkin_override_warnings_requires_reason(carto_tmp, installed_widget):
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\ntimeout = int(os.getenv("TIMEOUT", "30"))\n')
    result = carto_tmp.checkin(installed_widget, reason="Test",
                               override_warnings=True, override_reason="")
    assert result["status"] == "error"


def test_checkin_override_warnings_with_reason_succeeds(carto_tmp, installed_widget):
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\ntimeout = int(os.getenv("TIMEOUT", "30"))\n')
    result = carto_tmp.checkin(
        installed_widget, reason="Configurable timeout",
        override_warnings=True,
        override_reason="os.getenv used for optional timeout, not project-specific",
    )
    assert result["status"] == "success"
    assert "override_reason" in result


def test_checkin_override_reason_in_changelog(carto_tmp, installed_widget):
    widget = next(w for w in carto_tmp.widgets if w["id"] == "http-client")
    src = os.path.join(installed_widget, "src")
    py_files = [f for f in os.listdir(src) if f.endswith(".py")]
    target = os.path.join(src, py_files[0])
    with open(target, "a") as f:
        f.write('\ntimeout = int(os.getenv("TIMEOUT", "30"))\n')
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
    target = str(tmp_path / "new-widget")
    result = carto_tmp.create("new-widget", language="python", name="New Widget",
                               domain="backend", tags=[], target_dir=target)
    assert result["status"] == "success"
    with open(os.path.join(target, "widget.json")) as f:
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
