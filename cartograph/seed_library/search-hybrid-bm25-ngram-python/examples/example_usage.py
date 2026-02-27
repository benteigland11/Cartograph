"""
Example usage of Hybrid BM25 + N-gram Search.

This file must run cleanly with no external dependencies or network calls.
Uses fake/hardcoded data to demonstrate the widget's logic.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from hybrid_bm25_ngram import HybridSearch

# Sample document collection
documents = [
    {"name": "Auth Middleware", "description": "JWT authentication for API routes", "tags": ["auth", "jwt"]},
    {"name": "Rate Limiter", "description": "Token bucket rate limiting", "tags": ["rate-limit", "throttle"]},
    {"name": "CSV Parser", "description": "Fast CSV parsing with streaming", "tags": ["csv", "data"]},
    {"name": "Redis Cache", "description": "Redis-backed caching with TTL", "tags": ["cache", "redis"]},
]

# Create engine with default field weights
engine = HybridSearch()
engine.index(documents)

# Exact match
results = engine.search("auth")
print("Query: 'auth'")
for r in results:
    print(f"  {r['name']} (score: {r['score']})")

# Fuzzy match (typo)
print("\nQuery: 'cahce' (typo)")
results = engine.search("cahce")
for r in results:
    print(f"  {r['name']} (score: {r['score']})")

# Custom field weights
engine2 = HybridSearch(fields={"name": 5.0, "description": 1.0, "tags": 3.0})
engine2.index(documents)
results = engine2.search("rate limit")
print("\nQuery: 'rate limit' (custom weights)")
for r in results:
    print(f"  {r['name']} (score: {r['score']})")
