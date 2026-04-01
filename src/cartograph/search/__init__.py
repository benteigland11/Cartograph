"""
Search package for Cartograph.

Default backend: hybrid (TF-IDF + n-gram).
All backends are pure Python, zero external dependencies.

To add a new backend:
  1. Create search/<name>.py with a SearchBackend subclass
  2. Register it in _BACKENDS below
"""

from .base import SearchBackend
from .hybrid import HybridBackend
from .tfidf import TFIDFBackend

_BACKENDS: dict[str, type[SearchBackend]] = {
    "hybrid": HybridBackend,
    "tfidf":  TFIDFBackend,
}


def get_backend(name: str = "hybrid") -> SearchBackend:
    """Return an uninitialised backend instance. Call .build(widgets) before use."""
    cls = _BACKENDS.get(name.lower())
    if cls is None:
        available = ", ".join(_BACKENDS)
        raise ValueError(f"Unknown search backend '{name}'. Available: {available}")
    return cls()


__all__ = ["get_backend", "SearchBackend"]
