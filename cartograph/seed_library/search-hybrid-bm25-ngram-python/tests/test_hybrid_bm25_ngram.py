import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.hybrid_bm25_ngram import HybridSearch


DOCS = [
    {"name": "Auth Middleware", "description": "JWT authentication for API routes", "tags": ["auth", "jwt", "middleware"], "language": "python"},
    {"name": "Rate Limiter", "description": "Token bucket rate limiting", "tags": ["rate-limit", "throttle"], "language": "python"},
    {"name": "CSV Parser", "description": "Fast CSV parsing with streaming support", "tags": ["csv", "parser", "data"], "language": "python"},
    {"name": "Redis Cache", "description": "Redis-backed caching layer with TTL", "tags": ["cache", "redis"], "language": "go"},
    {"name": "Auth Client", "description": "OAuth2 client for third-party authentication", "tags": ["auth", "oauth", "client"], "language": "typescript"},
]


def _build_engine(docs=None):
    engine = HybridSearch()
    engine.index(docs or DOCS)
    return engine


def test_basic_search_returns_results():
    engine = _build_engine()
    results = engine.search("auth")
    assert len(results) > 0


def test_auth_query_ranks_auth_widgets_first():
    engine = _build_engine()
    results = engine.search("auth")
    names = [r["name"] for r in results]
    assert names[0] in ("Auth Middleware", "Auth Client")
    assert names[1] in ("Auth Middleware", "Auth Client")


def test_fuzzy_matching_handles_typos():
    engine = _build_engine()
    results = engine.search("atuh")
    assert len(results) > 0
    names = [r["name"] for r in results]
    assert any("Auth" in n for n in names)


def test_top_k_limits_results():
    engine = _build_engine()
    results = engine.search("a", top_k=2)
    assert len(results) <= 2


def test_empty_index_returns_empty():
    engine = HybridSearch()
    engine.index([])
    results = engine.search("anything")
    assert results == []


def test_filters_by_field():
    engine = _build_engine()
    results = engine.search("auth", filters={"language": "python"})
    for r in results:
        assert r["language"] == "python"


def test_results_have_score():
    engine = _build_engine()
    results = engine.search("cache")
    assert all("score" in r for r in results)
    assert all(r["score"] > 0 for r in results)


def test_results_sorted_by_score_descending():
    engine = _build_engine()
    results = engine.search("rate limit")
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_no_match_returns_empty():
    engine = _build_engine()
    results = engine.search("xyzzyplugh")
    assert results == []


def test_custom_fields():
    docs = [
        {"title": "Foo Bar", "body": "A thing about foos"},
        {"title": "Baz Qux", "body": "A thing about bazzes"},
    ]
    engine = HybridSearch(fields={"title": 3.0, "body": 1.0})
    engine.index(docs)
    results = engine.search("foo")
    assert len(results) > 0
    assert results[0]["title"] == "Foo Bar"


def test_synonym_expansion():
    engine = HybridSearch(synonyms={"auth": ["authentication", "login"]})
    engine.index(DOCS)
    results = engine.search("login")
    names = [r["name"] for r in results]
    assert any("Auth" in n for n in names)


def test_list_field_values():
    engine = _build_engine()
    results = engine.search("middleware")
    assert len(results) > 0
    assert results[0]["name"] == "Auth Middleware"


def test_exact_boost_surfaces_exact_matches():
    engine = _build_engine()
    results = engine.search("CSV Parser")
    assert results[0]["name"] == "CSV Parser"
