"""
Search package for Cartograph.

Default backend: hybrid (BM25 + n-gram).
All backends are pure Python, zero external service dependencies.

To add a new backend:
  1. Create search/<name>.py with a SearchBackend subclass
  2. Register it in _BACKENDS below
"""

from .base import SearchBackend
from .hybrid import HybridBackend
from .bm25 import BM25Backend

_BACKENDS: dict[str, type[SearchBackend]] = {
    "hybrid": HybridBackend,
    "bm25":   BM25Backend,
}


def get_backend(name: str = "hybrid") -> SearchBackend:
    """Return an uninitialised backend instance. Call .build(widgets) before use."""
    cls = _BACKENDS.get(name.lower())
    if cls is None:
        available = ", ".join(_BACKENDS)
        raise ValueError(f"Unknown search backend '{name}'. Available: {available}")
    return cls()


__all__ = ["get_backend", "SearchBackend"]
