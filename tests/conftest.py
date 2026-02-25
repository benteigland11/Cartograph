"""
Shared fixtures for Cartographer tests.
"""
import os
import sys
import pytest

# Ensure the repo root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
WIDGET_LIBRARY = os.path.join(FIXTURES_DIR, "Widget_Library")
BLUEPRINTS = os.path.join(FIXTURES_DIR, "Blueprints")


@pytest.fixture(scope="session")
def carto():
    """A Cartographer instance loaded against the test fixtures."""
    from cartographer import Cartographer
    return Cartographer(
        library_path=WIDGET_LIBRARY,
        blueprint_path=BLUEPRINTS,
        search_backend="bm25",
    )


@pytest.fixture(scope="session")
def widget_ids(carto):
    return {w["id"] for w in carto.widgets}
