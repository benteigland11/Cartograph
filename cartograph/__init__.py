"""Cartograph - widget library manager for AI agents."""

from importlib.metadata import version as _pkg_version

from .engine import Cartograph, LIBRARY_PATH

__version__ = _pkg_version("cartograph")
__all__ = ["Cartograph", "LIBRARY_PATH", "__version__"]
