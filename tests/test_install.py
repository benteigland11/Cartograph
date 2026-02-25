"""
Tests for install and uninstall.
install/uninstall return {"status": "error", "message": ...} on failure.
"""
import os
import pytest


@pytest.fixture
def fresh_carto(fixture_library, fixture_blueprints, tmp_path):
    """A fresh Cartographer instance with an isolated install dir."""
    from cartographer import Cartographer
    c = Cartographer(
        library_path=fixture_library,
        blueprint_path=fixture_blueprints,
        search_backend="bm25",
    )
    return c, tmp_path


def test_install_widget(fresh_carto):
    carto, install_dir = fresh_carto
    result = carto.install("http-client", str(install_dir))
    assert isinstance(result, dict)
    assert result.get("status") != "error", f"Install failed: {result.get('message')}"


def test_install_unknown_widget(fresh_carto):
    carto, install_dir = fresh_carto
    result = carto.install("no-such-widget-xyz", str(install_dir))
    assert result.get("status") == "error"


def test_install_creates_files(fresh_carto):
    carto, install_dir = fresh_carto
    carto.install("json-parser", str(install_dir))
    installed_files = list(install_dir.rglob("*"))
    assert len(installed_files) > 0


def test_uninstall_widget(fresh_carto):
    carto, install_dir = fresh_carto
    # Install into the default dir so the safety check passes
    default_install = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cartographer")
    carto.install("http-client", default_install)
    result = carto.uninstall("http-client")
    assert isinstance(result, dict)
    assert result.get("status") != "error", f"Uninstall failed: {result.get('message')}"


def test_uninstall_unknown_widget(fresh_carto):
    carto, install_dir = fresh_carto
    result = carto.uninstall("no-such-widget-xyz")
    assert result.get("status") == "error"
