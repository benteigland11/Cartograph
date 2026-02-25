"""
Tests for inspect and list_popular.
list_popular returns {"top_assets": [...]}
"""
import pytest


def test_inspect_known_widget(carto):
    result = carto.inspect("http-client")
    assert result is not None
    assert result.get("id") == "http-client"
    assert result.get("name") == "HTTP Client"


def test_inspect_unknown_widget(carto):
    result = carto.inspect("does-not-exist")
    assert result is not None
    assert "error" in result


def test_inspect_returns_version(carto):
    result = carto.inspect("http-client")
    assert "version" in result
    assert result["version"] == "1.2.0"


def test_inspect_returns_tags(carto):
    result = carto.inspect("http-client")
    assert "tags" in result
    assert "http" in result["tags"]


def test_inspect_blueprint(carto):
    result = carto.inspect("web-api-stack")
    assert result is not None
    assert result.get("type") == "blueprint"


def test_list_popular_returns_list(carto):
    result = carto.list_popular()
    assert isinstance(result, dict)
    assert "top_assets" in result
    assert isinstance(result["top_assets"], list)


def test_list_popular_limit(carto):
    result = carto.list_popular(limit=2)
    assert len(result["top_assets"]) <= 2


def test_list_popular_fields(carto):
    result = carto.list_popular()
    for item in result["top_assets"]:
        assert "id" in item
        assert "name" in item
