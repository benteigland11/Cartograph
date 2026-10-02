"""Where heavy dependencies live on this machine (glue).

A widget says *what* heavy dependency it needs - a name and, optionally, a
version in widget.json (``mathlib==v4.32.0``); never a path. The machine
says *where* heavy dependencies live: one store root, resolved from

    1. ``$CARTOGRAPH_HEAVY_DEPS_ROOT``
    2. ``cartograph config heavy-deps-root <dir>`` (config.toml)
    3. the user data dir (today's location - existing workspaces keep
       working with no re-provisioning)

Version ``v`` of dependency ``name`` lives at ``<root>/<store>/<v>/``,
where ``store`` is the folder registered for it in ``HEAVY_DEPS`` below.

The store root is deliberately separate from per-user state: credentials,
profile cache, registries, rules and config stay in the data dir. Because
sandboxes commonly redirect XDG_DATA_HOME (and with it config.toml), the
environment variable is the way to point a sandbox at a store provisioned
on the host.

Adding a second heavy dependency
--------------------------------
1. Register it in ``HEAVY_DEPS`` (dependency name -> store folder).
2. Its engine resolves the requested version with ``requested_version``
   and the directory with ``heavy_dep_dir(name, version)``; anything not
   provisioned there is a clear "provision it first" error naming the
   version and the command - never an automatic download.
3. Provisioning (if Cartograph offers it) is an explicit command that
   writes into ``heavy_dep_dir`` - see ``mathlib_setup`` for the pattern.

Path logic lives in the ``infra-heavy-deps-store-python`` widget; this
module wires it to the environment, config.toml and the data dir.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Optional

from cg.infra_heavy_deps_store_python.src.heavy_deps_store import (
    StoreRoot,
    dependency_dir,
    resolve_root,
    version_dir,
)

HEAVY_DEPS_ROOT_ENV = "CARTOGRAPH_HEAVY_DEPS_ROOT"
CONFIG_SECTION = "heavy_deps"
CONFIG_KEY = "root"


@dataclass(frozen=True)
class HeavyDep:
    """A dependency served from the shared store instead of per widget."""

    name: str                         # as declared in widget.json
    store: str                        # folder under the store root
    legacy_env: Optional[str] = None  # deprecated var naming <root>/<store>


HEAVY_DEPS: Dict[str, HeavyDep] = {
    "mathlib": HeavyDep("mathlib", "lean-mathlib",
                        legacy_env="CARTOGRAPH_MATHLIB_ROOT"),
}


def _configured_root() -> Optional[str]:
    from .config import load_config
    value = load_config().get(CONFIG_SECTION, {})
    value = value.get(CONFIG_KEY) if isinstance(value, dict) else None
    return value if isinstance(value, str) else None


def _default_root() -> str:
    from .engine import _user_data_dir
    return _user_data_dir()


def heavy_deps_root() -> StoreRoot:
    """The store root for every heavy dependency, and where it came from."""
    return resolve_root(
        [(HEAVY_DEPS_ROOT_ENV, os.environ.get(HEAVY_DEPS_ROOT_ENV)),
         ("config heavy-deps-root", _configured_root())],
        default=_default_root(), default_label="data dir")


def heavy_dep_store(name: str) -> StoreRoot:
    """Folder holding every version of heavy dependency ``name``.

    A dependency's deprecated per-dependency variable (``legacy_env``)
    names this folder directly; it applies only when
    ``CARTOGRAPH_HEAVY_DEPS_ROOT`` is unset, and beats config.toml.
    """
    dep = _registered(name)
    legacy = (os.environ.get(dep.legacy_env) or "").strip() \
        if dep.legacy_env else ""
    if legacy and not (os.environ.get(HEAVY_DEPS_ROOT_ENV) or "").strip():
        return resolve_root([(f"{dep.legacy_env} (deprecated)", legacy)],
                            default=legacy)
    root = heavy_deps_root()
    return StoreRoot(dependency_dir(root.path, dep.store), root.source)


def heavy_dep_dir(name: str, version: str) -> str:
    """Directory for ``version`` of heavy dependency ``name``.

    Raises ValueError for a version that is not a single path segment.
    """
    store = heavy_dep_store(name).path
    return str(version_dir(store.parent, store.name, version))


# widget.json carries a heavy dependency as ``name`` (engine default
# version) or ``name==<version>`` (exact); the dict form
# ``{"name": ..., "version": ...}`` is accepted too.
_EXACT_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*(\S+)\s*$")
_OPERATOR_RE = re.compile(r"[<>=!~]")


def requested_version(dep) -> Optional[str]:
    """The exact version a widget dependency entry asks for, or None.

    Raises ValueError when the entry uses a range (``>=``, ``~=``...): a
    heavy dependency is one provisioned directory, so only an exact
    version can name it.
    """
    if isinstance(dep, dict):
        value = dep.get("version") or dep.get("pin")
        return str(value).strip() if value else None
    text = str(dep or "")
    match = _EXACT_RE.match(text)
    if match:
        return match.group(2)
    if _OPERATOR_RE.search(text):
        name = _OPERATOR_RE.split(text)[0].strip()
        raise ValueError(
            f"`{text.strip()}`: a heavy dependency names one provisioned "
            f"version - use `{name}==<version>` or just `{name}` for the "
            "engine's default")
    return None


def _registered(name: str) -> HeavyDep:
    try:
        return HEAVY_DEPS[name]
    except KeyError:
        raise KeyError(f"{name!r} is not a registered heavy dependency")
