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
    "nim": frozenset({"nimcache", "htmldocs", "nimble.paths", "nimble.develop"}),
    "openscad": frozenset(),
    "systemverilog": frozenset({"work", "transcript"}),
    "ruby": frozenset({"vendor", ".bundle", "tmp"}),
    "elixir": frozenset({"_build", "deps", "cover"}),
    "swift": frozenset({".build", ".swiftpm", "Pods"}),
    "dart": frozenset({".dart_tool", "build"}),
    "terraform": frozenset({".terraform"}),
}


# Prefix patterns matched against directory or file basenames, with any
# leading dots stripped before comparison. Catches non-standard variants
# like `.nimcache_example` that exact-name matching misses.
_PREFIX_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "nim": frozenset({"nimcache"}),
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


def prefix_excludes_for(
    language: str | None = None,
    languages: Iterable[str] = (),
) -> frozenset[str]:
    """Return prefix patterns for the given language(s).

    A name matches a prefix when, after stripping any leading dots, it
    starts with the prefix. Example: prefix ``nimcache`` matches
    ``nimcache``, ``.nimcache_example``, and ``nimcache_old``.
    """
    result: set[str] = set()
    tags: list[str] = []
    if language is not None:
        tags.append(language)
    tags.extend(languages)
    for tag in tags:
        result.update(_PREFIX_BY_LANGUAGE.get(tag.lower(), frozenset()))
    return frozenset(result)


def _matches_prefix(name: str, prefixes: Iterable[str]) -> bool:
    if not name:
        return False
    stripped = name.lstrip(".")
    return any(stripped.startswith(p) for p in prefixes)


def all_known_excludes() -> frozenset[str]:
    """Return the union across every known language. Catch-all when the
    consumer doesn't know which ecosystems live in a tree."""
    result = set(_UNIVERSAL)
    for entries in _BY_LANGUAGE.values():
        result.update(entries)
    return frozenset(result)


def should_skip(
    path: str,
    excludes: Iterable[str],
    prefixes: Iterable[str] = (),
) -> bool:
    """Return True if any path component matches an exclude entry.

    Designed for use inside ``os.walk`` loops or against a relative
    path inside a zip-build loop. ``prefixes`` is checked with leading
    dots stripped (so ``nimcache`` matches ``.nimcache_example``).
    """
    exclude_set = set(excludes)
    prefix_tuple = tuple(prefixes)
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if not part:
            continue
        if part in exclude_set:
            return True
        if prefix_tuple and _matches_prefix(part, prefix_tuple):
            return True
    return False


def filter_dirs(
    dirs: list[str],
    excludes: Iterable[str],
    prefixes: Iterable[str] = (),
) -> list[str]:
    """Return a new list with excluded entries removed. Convenience
    wrapper for the common ``dirs[:] = filter_dirs(dirs, excludes)``
    pattern inside ``os.walk``. ``prefixes`` is checked with leading
    dots stripped."""
    exclude_set = set(excludes)
    prefix_tuple = tuple(prefixes)
    return [
        d for d in dirs
        if d not in exclude_set
        and not (prefix_tuple and _matches_prefix(d, prefix_tuple))
    ]


def supported_languages() -> tuple[str, ...]:
    """Return the language tags this widget knows about."""
    return tuple(sorted(_BY_LANGUAGE.keys()))
