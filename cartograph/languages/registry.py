"""
Language engine registry.

Maps language name strings (as they appear in widget.json tech_stack.language)
to the appropriate LanguageEngine subclass instance.

To add a new language (see base.py for the full checklist):
  1. Import the engine class and add it to _ENGINES under its canonical name
  2. Add short aliases to _ALIASES if needed (e.g. "rs" -> "rust")
  3. Add a scaffold template in scaffolding/templates.py

The language will automatically appear in supported_languages() and all
error messages once its engine has supported = True.
"""

from .python import PythonEngine
from .javascript import JavaScriptEngine, TypeScriptEngine
from .nim import NimEngine
from .base import LanguageEngine

# Canonical language name -> engine instance.
# Add an entry here when a new language engine is ready for validation.
_ENGINES = {
    "python": PythonEngine(),
    "javascript": JavaScriptEngine(),
    "typescript": TypeScriptEngine(),
    "nim": NimEngine(),
}

_ALIASES = {"js": "javascript", "ts": "typescript"}

def get_engine(language: str) -> LanguageEngine | None:
    """Return the engine for a language string, or None if unknown."""
    key = language.lower().strip()
    key = _ALIASES.get(key, key)
    return _ENGINES.get(key)


def supported_languages() -> list[str]:
    """Return languages with full validation support — derived from _ENGINES."""
    return sorted(name for name, engine in _ENGINES.items() if engine.supported)
