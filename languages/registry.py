"""
Language engine registry.

Maps language name strings (as they appear in widget.json tech_stack.language)
to the appropriate LanguageEngine subclass instance.

To add a new language:
  1. Create languages/<lang>.py with a LanguageEngine subclass
  2. Import and register it here
"""

from .python import PythonEngine
from .base import LanguageEngine

# v0.1: only Python validation is supported.
# Other language engine files exist but are not wired in yet.
_PYTHON_ENGINE = PythonEngine()

_V01_UNSUPPORTED = frozenset([
    "javascript", "typescript", "js", "ts",
    "go",
    "rust",
    "cpp", "c", "c++", "hip",
    "csharp", "c#", "dotnet",
    "java", "kotlin", "maven", "gradle",
])


class _UnsupportedEngine(LanguageEngine):
    """Placeholder returned for languages not yet validated in v0.1."""
    def __init__(self, language: str):
        self.name = language

    def install_deps(self, path: str, dependencies: list) -> None:
        pass

    def run_tests(self, path: str) -> dict:
        return {"passed": False,
                "error": f"'{self.name}' validation is not supported in v0.1 — only Python widgets are validated."}


def get_engine(language: str) -> LanguageEngine | None:
    """Return the engine for a language string, or None if unknown.

    v0.1: only Python returns a real engine. All other known languages
    return an UnsupportedEngine stub so callers get a clear error instead
    of a silent None.
    """
    key = language.lower().strip()
    if key == "python":
        return _PYTHON_ENGINE
    if key in _V01_UNSUPPORTED:
        return _UnsupportedEngine(key)
    return None


def supported_languages() -> list[str]:
    """Return languages with full validation support in this release."""
    return ["python"]
