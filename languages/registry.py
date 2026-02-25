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
from .go import GoEngine
from .rust import RustEngine
from .cpp import CppEngine, CEngine
from .dotnet import DotNetEngine
from .jvm import MavenEngine, GradleEngine
from .base import LanguageEngine

_engines: dict[str, LanguageEngine] = {}

def _register(*engine_classes):
    for cls in engine_classes:
        instance = cls()
        _engines[instance.name] = instance

_register(
    PythonEngine,
    JavaScriptEngine,
    TypeScriptEngine,
    GoEngine,
    RustEngine,
    CppEngine,
    CEngine,
    DotNetEngine,
    MavenEngine,
    GradleEngine,
)

# Aliases for common alternate spellings in widget.json
_aliases = {
    "js": "javascript",
    "ts": "typescript",
    "c++": "cpp",
    "java": "java",
    "kotlin": "kotlin",
    "c#": "csharp",
    "hip": "cpp",   # AMD HIP uses C++ toolchain
}


def get_engine(language: str) -> LanguageEngine | None:
    """
    Return the engine for a language string, or None if unsupported.
    Case-insensitive. Returns None rather than raising so callers can
    decide how to handle unknown languages gracefully.
    """
    key = language.lower().strip()
    if key in _engines:
        return _engines[key]
    if key in _aliases:
        return _engines.get(_aliases[key])
    return None


def supported_languages() -> list[str]:
    """Return all registered language names."""
    return sorted(_engines.keys())
