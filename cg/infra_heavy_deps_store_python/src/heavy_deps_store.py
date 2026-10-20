"""Versioned store for heavy, pre-provisioned dependencies.

A heavy dependency (a multi-GB library, a pinned toolchain workspace, a
model checkpoint) is provisioned once per machine and shared by every
consumer. This widget owns only the *where*: one store root, chosen from
an ordered list of caller-supplied layers (for example an environment
variable, then a config value, then a default), and a deterministic
layout under it::

    <root>/<name>/<version>/

Consumers say *what* they need as a ``(name, version)`` pair; the root is
machine state. The widget never reads the environment or config itself,
never creates directories, and never provisions anything - callers pass
the layer values in and own provisioning.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]
Layer = Tuple[str, Optional[str]]


@dataclass(frozen=True)
class StoreRoot:
    """The resolved store root and the label of the layer that supplied it."""

    path: Path
    source: str


def resolve_root(layers: Sequence[Layer], default: PathLike,
                 default_label: str = "default") -> StoreRoot:
    """Pick the store root from ordered ``(label, value)`` layers.

    The first layer whose value is a non-blank string wins; ``~`` is
    expanded and the result made absolute. When every layer is blank or
    ``None``, ``default`` is used under ``default_label``.
    """
    for label, value in layers:
        if value is not None and str(value).strip():
            return StoreRoot(_normalise(str(value).strip()), label)
    return StoreRoot(_normalise(str(default)), default_label)


def dependency_dir(root: PathLike, name: str) -> Path:
    """Directory holding every provisioned version of ``name``."""
    _validate_segment(name, "dependency name")
    return Path(root) / name


def version_dir(root: PathLike, name: str, version: str) -> Path:
    """Directory holding version ``version`` of dependency ``name``."""
    _validate_segment(version, "version")
    return dependency_dir(root, name) / version


def installed_versions(root: PathLike, name: str,
                       marker: Optional[str] = None) -> List[str]:
    """Sorted version directories present for ``name``.

    With ``marker``, only versions containing that file count (callers
    pass the file their provisioning writes last, so half-provisioned
    versions are not listed).
    """
    base = dependency_dir(root, name)
    if not base.is_dir():
        return []
    found = []
    for entry in base.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if marker is not None and not (entry / marker).is_file():
            continue
        found.append(entry.name)
    return sorted(found)


def _normalise(value: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(value)))


def _validate_segment(value: str, what: str) -> None:
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(c in value for c in "/\\") or value in (".", "..")):
        raise ValueError(
            f"invalid {what} {value!r}: must be a non-empty single path "
            "segment")
