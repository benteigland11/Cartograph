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

_PYTHON_ENGINE = PythonEngine()
_JS_ENGINE = JavaScriptEngine()
_TS_ENGINE = TypeScriptEngine()

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
        return {"passed": False,
                "error": f"'{self.name}' is not supported. Supported languages: python, javascript."}


def get_engine(language: str) -> LanguageEngine | None:
    """Return the engine for a language string, or None if unknown.

    v0.1: only Python returns a real engine. All other known languages
    return an UnsupportedEngine stub so callers get a clear error instead
    of a silent None.
    """
    key = language.lower().strip()
    if key == "python":
        return _PYTHON_ENGINE
    if key in ("javascript", "js"):
        return _JS_ENGINE
    if key in ("typescript", "ts"):
        return _TS_ENGINE
    if key in _V01_UNSUPPORTED:
        return _UnsupportedEngine(key)
    return None


def supported_languages() -> list[str]:
    """Return languages with full validation support in this release."""
    return ["python", "javascript"]
