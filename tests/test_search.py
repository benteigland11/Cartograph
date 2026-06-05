"""
Tests for search, filtering, and result formatting.
"""
import pytest


def test_search_returns_dict(carto):
    result = carto.search("http")
    assert isinstance(result, dict)
    assert "results" in result


def test_search_finds_widget_by_name(carto):
    result = carto.search("http client")
    ids = [w["id"] for w in result["results"]]
    assert "http-client" in ids


def test_search_finds_widget_by_tag(carto):
    result = carto.search("jwt")
    ids = [w["id"] for w in result["results"]]
    assert "auth-middleware" in ids


def test_search_finds_widget_by_description(carto):
    result = carto.search("schema validation")
    ids = [w["id"] for w in result["results"]]
    assert "json-parser" in ids


def test_search_no_results_for_garbage(carto):
    result = carto.search("xyzzy_qqqq_zzzzzzzzz_abc")
    assert result["results"] == []


def test_search_domain_filter(carto):
    result = carto.search("auth", domain_filter="frontend")
    # auth-middleware is backend, should not appear under frontend filter
    ids = [w["id"] for w in result["results"]]
    assert "auth-middleware" not in ids


def test_search_language_filter(carto):
    result = carto.search("parser", language_filter="python")
    ids = [w["id"] for w in result["results"]]
    assert "json-parser" in ids


def test_search_result_fields(carto):
    result = carto.search("http")
    for item in result["results"]:
        assert "id" in item
        assert "name" in item
        assert "description" in item
        assert "language" in item
        assert "domain" in item
        assert "rating" in item
        assert "install_count" in item
        assert "relevance_score" in item


def test_search_sorted_by_relevance(carto):
    result = carto.search("json")
    scores = [w["relevance_score"] for w in result["results"]]
    assert scores == sorted(scores, reverse=True)


def test_search_empty_library():
    """Search on a Cartograph with no widgets returns empty result."""
    from cartograph import Cartograph
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        lib = os.path.join(tmp, "Widget_Library")
        os.makedirs(lib)
        c = Cartograph(library_path=lib)
        result = c.search("anything")
    assert result == {"results": []}


def test_search_top_k_respected(carto):
    result = carto.search("backend", top_k=2)
    assert len(result["results"]) <= 2


# ---------------------------------------------------------------------------
# Search row contract (cli._search_row) — bounded rows for predictable payload
# ---------------------------------------------------------------------------

def test_search_row_drops_trend():
    from cartograph.cli import _search_row
    row = _search_row({"id": "x", "trend": "up", "rating": 4.5})
    assert "trend" not in row
    assert row["rating"] == 4.5


def test_search_row_truncates_long_description_at_word_boundary():
    from cartograph.cli import _search_row, _SEARCH_DESC_LIMIT
    desc = "word " * 100  # 500 chars
    row = _search_row({"id": "x", "description": desc})
    assert row["description"].endswith("...")
    assert len(row["description"]) <= _SEARCH_DESC_LIMIT + 3
    # No mid-word cut: everything before the ellipsis is whole words
    assert row["description"][:-3].split(" ")[-1] == "word"


def test_search_row_keeps_short_description_untouched():
    from cartograph.cli import _search_row
    row = _search_row({"id": "x", "description": "Short and sweet."})
    assert row["description"] == "Short and sweet."


def test_search_row_does_not_mutate_input():
    from cartograph.cli import _search_row
    original = {"id": "x", "trend": "up", "description": "d" * 999}
    _search_row(original)
    assert original["trend"] == "up"
    assert len(original["description"]) == 999
