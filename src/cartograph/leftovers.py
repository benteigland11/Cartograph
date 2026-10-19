"""What a widget's example or tests left running: processes they started that outlived them.

Validation runs the example and the tests as a child subreaper (Linux `PR_SET_CHILD_SUBREAPER`): a process they start
and abandon is reparented to the validator instead of to PID 1, so whatever is still the validator's afterwards,
with everything under it, is what they failed to shut down. Validation names those processes, stops them and fails.
The source itself may start something meant to outlive a call (a service); the example and the tests show it stopped.

The subreaper, not an environment marker, is what finds a browser: chromium rewrites its own environment block when it
sets its process title, so a marker it inherited cannot be read back from it. A marker is still set (and read) for a
process left attached to some other live parent. A widget used in a long-lived loop that leaks a process per call
piles up: twelve orphaned chromium trees, 3.9 GB, over one night of page probes (2026-09-24); the place to catch that
is before the widget enters the library, not after.

Elsewhere than Linux the check sees nothing and reports nothing rather than failing.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

MARK = "CARTOGRAPH_VALIDATION_RUN"
GRACE_SECONDS = 3.0
_PR_SET_CHILD_SUBREAPER = 36


def _subreaper(on: bool) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_SET_CHILD_SUBREAPER, 1 if on else 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def _table() -> dict[int, dict[str, Any]]:
    """Every process: parent, state, command, and its environment block (to look for `MARK`)."""
    root = Path("/proc")
    out: dict[int, dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            tail = stat[stat.rfind(")") + 2:].split()
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            try:
                env = (entry / "environ").read_bytes()
            except OSError:
                env = b""
        except (OSError, IndexError):
            continue
        out[int(entry.name)] = {"pid": int(entry.name), "ppid": int(tail[1]), "state": tail[0],
                                "command": cmd[:160] or stat[stat.find("(") + 1:stat.rfind(")")], "env": env}
    return out


def _descendants(table: dict[int, dict[str, Any]], roots: set[int]) -> set[int]:
    found, frontier = set(roots), set(roots)
    while frontier:
        frontier = {p for p, info in table.items() if info["ppid"] in frontier and p not in found}
        found |= frontier
    return found


def _left(me: int, before: set[int], token: str) -> list[dict[str, Any]]:
    table = _table()
    needle = f"{MARK}={token}".encode()
    adopted = {p for p, info in table.items() if info["ppid"] == me and p not in before}
    marked = {p for p, info in table.items() if needle in info["env"].split(b"\0") and p != me}
    pids = _descendants(table, adopted | marked)
    return [{k: table[p][k] for k in ("pid", "ppid", "command")} for p in sorted(pids)
            if p in table and table[p]["state"] != "Z"]


def _reap_zombies(me: int, before: set[int]) -> None:
    """Orphans that exited on their own while we were their subreaper: collect them so they do not linger."""
    for p, info in _table().items():
        if info["ppid"] == me and info["state"] == "Z" and p not in before:
            try:
                os.waitpid(p, os.WNOHANG)
            except ChildProcessError:
                pass


def run_tracked(run: Callable[[], Any], grace: float = GRACE_SECONDS) -> tuple[Any, list[dict[str, Any]]]:
    """Run `run()` with abandoned processes reparented to us; return its result and what it left running (stopped)."""
    me = os.getpid()
    before = {p for p, info in _table().items() if info["ppid"] == me}
    token = uuid.uuid4().hex
    previous = os.environ.get(MARK)
    os.environ[MARK] = token
    reaping = _subreaper(True)
    left: list[dict[str, Any]] = []
    try:
        outcome = run()
        deadline = time.monotonic() + grace
        left = _left(me, before, token)
        while left and time.monotonic() < deadline:
            time.sleep(0.1)
            _reap_zombies(me, before)
            left = _left(me, before, token)
        if left:
            stop(left)
        _reap_zombies(me, before)
    finally:
        if reaping:
            _subreaper(False)
        if previous is None:
            os.environ.pop(MARK, None)
        else:
            os.environ[MARK] = previous
    return outcome, left


def stop(processes: list[dict[str, Any]]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in processes:
            try:
                os.kill(p["pid"], sig)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.5)
    for p in processes:
        try:
            os.waitpid(p["pid"], os.WNOHANG)
        except ChildProcessError:
            pass


def describe(processes: list[dict[str, Any]]) -> str:
    pids = {q["pid"] for q in processes}
    roots = [p for p in processes if p["ppid"] not in pids] or processes
    shown = "; ".join(f"{p['command']} (pid {p['pid']})" for p in roots[:6])
    more = f"; and {len(roots) - 6} more" if len(roots) > 6 else ""
    return (f"{len(processes)} process(es) still running after it finished, from: {shown}{more}. A widget's example "
            f"and tests must shut down everything they start: close what they opened (a `with` block, try/finally, a "
            f"fixture's teardown), including on failure.")
