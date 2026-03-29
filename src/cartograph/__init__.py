"""Cartograph - widget library manager for AI agents."""

from importlib.metadata import version as _pkg_version

from .engine import Cartograph, LIBRARY_PATH

try:
    __version__ = _pkg_version("cartograph-cli")
except Exception:
    __version__ = "0.0.0"
__all__ = ["Cartograph", "LIBRARY_PATH", "__version__"]
