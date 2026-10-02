"""Shared Mathlib workspaces for the Lean engine (glue).

One shared workspace per Mathlib pin, in the heavy-dependency store
(``<heavy-deps root>/lean-mathlib/<pin>/``, see ``heavy_deps``). A widget
that declares ``mathlib==<pin>`` builds against that pin's workspace; a
bare ``mathlib`` gets the engine default, ``MATHLIB_PIN``. Workspaces are
provisioned explicitly via ``cartograph setup-mathlib [--pin <pin>]`` and
never automatically (same policy as the ML frameworks: heavy dependencies
must be pre-installed, with a clear "install it first" error otherwise).

The toolchain a widget builds with comes from the workspace's own
``lean-toolchain`` file, so it always matches the workspace's ``.olean``
files whatever pin it holds.

Lifecycle logic lives in ``infra-mathlib-workspace-python``; this module
wires it to the heavy-dependency store, the interprocess lock, and
subprocess execution.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable, Optional

from cg.infra_mathlib_workspace_python.src.mathlib_workspace import (
    STATE_CORRUPT,
    ProvisionResult,
    WorkspaceStatus,
    provision,
    status,
    workspace_path,
    workspace_toolchain,
)
from cg.infra_interprocess_lock_python.src.interprocess_lock import file_lock

from .heavy_deps import heavy_dep_store, requested_version

# The default Mathlib revision: what a widget declaring a bare `mathlib`
# validates against. Bumping it is a release decision: such widgets
# re-validate on next checkin (engine-bump policy), never retroactively.
MATHLIB_PIN = "v4.32.0"
# Toolchain used to provision MATHLIB_PIN. Builds read the toolchain from
# the workspace itself, never from this constant.
MATHLIB_TOOLCHAIN = "leanprover/lean4:v4.32.0"

_PROVISION_TIMEOUT = 3600  # cache download + root elaboration

# Mathlib's release tags track Lean releases one-to-one (v4.32.0 builds on
# leanprover/lean4:v4.32.0), so a tag pin implies its toolchain.
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+(-rc\d+)?$")


def mathlib_root() -> str:
    """Folder holding every provisioned Mathlib pin."""
    return str(heavy_dep_store("mathlib").path)


def mathlib_root_source() -> str:
    """Which setting chose ``mathlib_root()`` (for status output)."""
    return heavy_dep_store("mathlib").source


def widget_mathlib_pin(dependencies) -> Optional[str]:
    """The pin a widget's dependency list asks for.

    None when the widget declares no mathlib dependency; ``MATHLIB_PIN``
    for a bare ``mathlib``. Raises ValueError for a range or a pin that is
    not a single path segment.
    """
    from .languages.base import _dep_bare_name
    for dep in dependencies or []:
        if _dep_bare_name(dep) != "mathlib":
            continue
        pin = requested_version(dep) or MATHLIB_PIN
        workspace_path(mathlib_root(), pin)  # validates the segment
        return pin
    return None


def default_toolchain(pin: str) -> Optional[str]:
    """Toolchain to provision ``pin`` with when none is given, or None."""
    if pin == MATHLIB_PIN:
        return MATHLIB_TOOLCHAIN
    if _RELEASE_TAG.match(pin):
        return f"leanprover/lean4:{pin}"
    return None


def mathlib_toolchain(pin: str = MATHLIB_PIN) -> Optional[str]:
    """Toolchain the provisioned workspace for ``pin`` was built with."""
    return workspace_toolchain(mathlib_root(), pin)


def mathlib_status(pin: str = MATHLIB_PIN) -> WorkspaceStatus:
    toolchain = mathlib_toolchain(pin)
    state = status(mathlib_root(), pin, toolchain)
    if state.ready and toolchain is None:
        return WorkspaceStatus(
            STATE_CORRUPT, "workspace has no lean-toolchain file - "
            "re-provision it", state.path)
    return state


def mathlib_package_dir(pin: str = MATHLIB_PIN) -> str:
    """Path to the resolved Mathlib package inside the pin's workspace."""
    ws = workspace_path(mathlib_root(), pin)
    return os.path.join(str(ws), ".lake", "packages", "mathlib")


def setup_command(pin: str = MATHLIB_PIN) -> str:
    return ("cartograph setup-mathlib" if pin == MATHLIB_PIN
            else f"cartograph setup-mathlib --pin {pin}")


def missing_workspace_error(state_reason: str,
                            pin: str = MATHLIB_PIN) -> str:
    return (
        f"This widget declares a `mathlib` dependency (pin {pin}) but the "
        f"shared Mathlib workspace for {pin} is not ready ({state_reason}) "
        f"under {mathlib_root()}. Cartograph never downloads Mathlib "
        "automatically - provision it once with:\n"
        f"    {setup_command(pin)}\n"
        "(multi-GB download; set CARTOGRAPH_HEAVY_DEPS_ROOT or "
        "`cartograph config heavy-deps-root` if it lives elsewhere)"
    )


def setup_mathlib(
        runner: Optional[Callable] = None,
        progress: Optional[Callable[[str], None]] = None,
        pin: str = MATHLIB_PIN,
        toolchain: Optional[str] = None) -> ProvisionResult:
    """Provision the shared workspace for ``pin`` (idempotent, locked).

    ``toolchain`` defaults to ``default_toolchain(pin)``; a pin with no
    implied toolchain (not a release tag) must name one. ``runner``
    defaults to streaming subprocess execution; injectable for tests.
    ``progress`` receives one line per step when given.
    """
    toolchain = toolchain or default_toolchain(pin)
    if not toolchain:
        raise ValueError(
            f"pin {pin!r} is not a Mathlib release tag, so its toolchain "
            "cannot be inferred - pass one (e.g. --toolchain "
            "leanprover/lean4:v4.32.0)")
    workspace_path(mathlib_root(), pin)  # validates the pin
    root = mathlib_root()
    os.makedirs(root, exist_ok=True)

    def _default_runner(args, cwd):
        if progress:
            progress(f"running: {' '.join(args)}")
        proc = subprocess.run(list(args), cwd=cwd,
                              timeout=_PROVISION_TIMEOUT)
        return proc.returncode

    run = runner or _default_runner
    with file_lock(os.path.join(root, ".provision.lock")):
        current = mathlib_status(pin)
        if current.ready:
            return ProvisionResult(status=current)
        return provision(root, pin, toolchain, run)
