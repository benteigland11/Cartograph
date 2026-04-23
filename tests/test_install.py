"""
Tests for install and uninstall.
"""
import os
import pytest


@pytest.fixture
def fresh_carto(fixture_library, tmp_path):
    """A fresh Cartograph instance with an isolated install dir."""
    from cartograph import Cartograph
    c = Cartograph(
        library_path=fixture_library,
    )
    return c, str(tmp_path)


def _widget_path(target, widget_id):
    """Widgets now live at <project_root>/cg/<widget_id>."""
    return os.path.join(target, "cg", widget_id)


def test_install_widget(fresh_carto):
    carto, target = fresh_carto
    result = carto.install("http-client", target)
    assert result.get("status") == "success"
    assert result["widget_id"] == "http-client"
    assert result["version"] == "1.2.0"
    assert os.path.isdir(result["installed_at"])


def test_install_unknown_widget(fresh_carto):
    carto, target = fresh_carto
    result = carto.install("no-such-widget-xyz", target)
    assert "error" in result


def test_install_creates_files(fresh_carto):
    carto, target = fresh_carto
    carto.install("json-parser", target)
    widget_dir = _widget_path(target, "json-parser")
    assert os.path.exists(os.path.join(widget_dir, "widget.json"))
    assert os.path.isdir(os.path.join(widget_dir, "src"))


def test_install_duplicate_blocked(fresh_carto):
    carto, target = fresh_carto
    carto.install("http-client", target)
    result = carto.install("http-client", target)
    assert "error" in result
    assert "already installed" in result["error"].lower()


def test_install_rejects_relative_path(fresh_carto):
    carto, _ = fresh_carto
    result = carto.install("http-client", "relative/path")
    assert "error" in result


def test_uninstall_widget(fresh_carto):
    carto, target = fresh_carto
    carto.install("http-client", target)
    result = carto.uninstall("http-client", target)
    assert result.get("status") == "success"
    assert not os.path.exists(_widget_path(target, "http-client"))


def test_uninstall_not_installed(fresh_carto):
    carto, target = fresh_carto
    result = carto.uninstall("http-client", target)
    assert "error" in result


# ---------------------------------------------------------------------------
# Language-specific file preservation on install
# ---------------------------------------------------------------------------

def test_install_python_has_init(fresh_carto):
    """Python widget install should include src/__init__.py."""
    carto, target = fresh_carto
    result = carto.install("http-client", target)
    assert result.get("status") == "success"
    widget_dir = result["installed_at"]
    assert os.path.exists(os.path.join(widget_dir, "src", "__init__.py"))


def test_install_nim_has_nimble(fresh_carto):
    """Nim widget install should include the .nimble file."""
    carto, target = fresh_carto
    result = carto.install("universal-add-nim", target)
    assert result.get("status") == "success"
    widget_dir = result["installed_at"]
    nimble_files = [f for f in os.listdir(widget_dir) if f.endswith(".nimble")]
    assert len(nimble_files) == 1, f"Expected 1 .nimble file, found: {nimble_files}"


def test_install_js_has_package_json(fresh_carto):
    """JS widget install should include package.json."""
    carto, target = fresh_carto
    result = carto.install("data-sum-javascript", target)
    assert result.get("status") == "success"
    widget_dir = result["installed_at"]
    assert os.path.exists(os.path.join(widget_dir, "package.json"))


# ---------------------------------------------------------------------------
# Prefixed install: commands use the prefixed id throughout
# ---------------------------------------------------------------------------

def test_uninstall_prefixed_id(fresh_carto, fixture_library):
    """Uninstalling a widget using its prefixed id should work.

    The installed dir name IS the widget_id — cg-http-client installs to
    cg/cg-http-client/ and is uninstalled the same way.
    """
    import json
    from cartograph import Cartograph
    from cartograph.installer import _widget_dir
    carto, target = fresh_carto

    # Simulate a prefixed install: the dir name matches the prefixed id
    prefixed_id = "cg-http-client"
    wdir = _widget_dir(target, prefixed_id)
    os.makedirs(os.path.join(wdir, "src"), exist_ok=True)
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump({"meta": {"id": "http-client", "version": "1.0.0"}}, f)

    result = carto.uninstall(prefixed_id, target)
    assert result.get("status") == "success", result
    assert not os.path.isdir(wdir)


def test_status_prefixed_id(fresh_carto, fixture_library):
    """Status check with a prefixed id resolves the library entry via bare id."""
    import json
    from cartograph.installer import _widget_dir
    carto, target = fresh_carto

    prefixed_id = "cg-http-client"
    wdir = _widget_dir(target, prefixed_id)
    os.makedirs(os.path.join(wdir, "src"), exist_ok=True)
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump({"meta": {"id": "http-client", "version": "1.2.0"}}, f)

    result = carto.widget_status(widget_id=prefixed_id, target_dir=target)
    assert "error" not in result, result
    assert result["widget_id"] == prefixed_id
