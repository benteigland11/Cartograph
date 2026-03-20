"""
Language engine registry.

Maps language name strings (as they appear in widget.json tech_stack.language)
to the appropriate LanguageEngine subclass instance.

To add a new language:
  1. Create languages/<lang>.py with a LanguageEngine subclass
  2. Import and register it here
"""

from .python import PythonEngine
from .javascript import JavaScriptEngine, TypeScriptEngine
from .base import LanguageEngine

# Canonical language name -> engine instance.
# Add an entry here when a new language engine is ready for validation.
_ENGINES = {
    "python": PythonEngine(),
    "javascript": JavaScriptEngine(),
    "typescript": TypeScriptEngine(),
}

_ALIASES = {"js": "javascript", "ts": "typescript"}

_V01_UNSUPPORTED = frozenset([
    "go",
    "rust",
    "cpp", "c", "c++", "hip",
    "csharp", "c#", "dotnet",
    "java", "kotlin", "maven", "gradle",
])


class _UnsupportedEngine(LanguageEngine):
    """Returned for known-but-unsupported languages. Fails fast with a clear message."""
    supported = False

    def __init__(self, language: str):
        self.name = language

    def install_deps(self, path: str, dependencies: list) -> None:
        pass

    def run_tests(self, path: str) -> dict:
        langs = ", ".join(supported_languages())
        return {"passed": False,
                "error": f"'{self.name}' is not supported for validation. Supported: {langs}."}


def get_engine(language: str) -> LanguageEngine | None:
    """Return the engine for a language string, or None if unknown.

    Known-but-unsupported languages return an UnsupportedEngine stub so
    callers get a clear error instead of a silent None.
    """
    key = language.lower().strip()
    key = _ALIASES.get(key, key)
    if key in _ENGINES:
        return _ENGINES[key]
    if key in _V01_UNSUPPORTED:
        return _UnsupportedEngine(key)
    return None


def supported_languages() -> list[str]:
    """Return languages with full validation support — derived from _ENGINES."""
    return sorted(name for name, engine in _ENGINES.items() if engine.supported)
