"""Canonical build-artifact directory exclusion lists.

Centralizes the dirnames that should never be archived, copied, scanned,
or otherwise crossed when walking a project tree. Framework-aware.
"""

from __future__ import annotations

import os
from typing import Iterable


# Universal: VCS, OS junk, IDE droppings, tool caches that show up
# regardless of language.
_UNIVERSAL: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".DS_Store",
    ".idea",
    ".vscode",
    ".cache",
    ".tmp",
})


# Per-language artifact dirs. Keys are short language tags; consumers
# pass whichever they're packaging. Unknown tags are ignored (no raise),
# so callers don't need to defend against typos.
_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "python": frozenset({
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ".tox", ".nox", ".coverage", "htmlcov", ".hypothesis",
        ".venv", "venv", "env",
        "build", "dist",
    }),
    "javascript": frozenset({
        "node_modules", "coverage", "dist", "build",
        ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
        ".yarn", ".pnpm-store", ".rush",
    }),
    "typescript": frozenset({
        "node_modules", "coverage", "dist", "build", "out-tsc",
        ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    }),
    "angular": frozenset({
        "node_modules", "coverage", "dist", "out-tsc", ".angular",
    }),
    "php": frozenset({
        "vendor", "coverage", ".phpunit.cache", ".phpunit.result.cache",
    }),
    "rust": frozenset({"target"}),
    "java": frozenset({"target", "build", ".gradle"}),
    "kotlin": frozenset({"build", ".gradle"}),
    "go": frozenset({"vendor", "bin"}),
    "nim": frozenset({"nimcache", "htmldocs"}),
    "openscad": frozenset(),
    "systemverilog": frozenset({"work", "transcript"}),
    "ruby": frozenset({"vendor", ".bundle", "tmp"}),
    "elixir": frozenset({"_build", "deps", "cover"}),
    "swift": frozenset({".build", ".swiftpm", "Pods"}),
    "dart": frozenset({".dart_tool", "build"}),
    "terraform": frozenset({".terraform"}),
}


def default_excludes() -> frozenset[str]:
    """Return the universal exclusion set (VCS, IDE, OS metadata)."""
    return _UNIVERSAL


def excludes_for(
    language: str | None = None,
    languages: Iterable[str] = (),
) -> frozenset[str]:
    """Return the union of universal and language-specific exclusions.

    Pass ``language`` for a single ecosystem or ``languages`` for a
    polyglot project. Unknown tags contribute nothing rather than raising.
    """
    result = set(_UNIVERSAL)
    tags: list[str] = []
    if language is not None:
        tags.append(language)
    tags.extend(languages)
    for tag in tags:
        result.update(_BY_LANGUAGE.get(tag.lower(), frozenset()))
    return frozenset(result)


def all_known_excludes() -> frozenset[str]:
    """Return the union across every known language. Catch-all when the
    consumer doesn't know which ecosystems live in a tree."""
    result = set(_UNIVERSAL)
    for entries in _BY_LANGUAGE.values():
        result.update(entries)
    return frozenset(result)


def should_skip(path: str, excludes: Iterable[str]) -> bool:
    """Return True if any path component matches an exclude entry.

    Designed for use inside ``os.walk`` loops or against a relative
    path inside a zip-build loop.
    """
    exclude_set = set(excludes)
    parts = path.replace("\\", "/").split("/")
    return any(part in exclude_set for part in parts if part)


def filter_dirs(dirs: list[str], excludes: Iterable[str]) -> list[str]:
    """Return a new list with excluded entries removed. Convenience
    wrapper for the common ``dirs[:] = filter_dirs(dirs, excludes)``
    pattern inside ``os.walk``."""
    exclude_set = set(excludes)
    return [d for d in dirs if d not in exclude_set]


def supported_languages() -> tuple[str, ...]:
    """Return the language tags this widget knows about."""
    return tuple(sorted(_BY_LANGUAGE.keys()))
