"""Tests for the safefs glue layer.

The underlying mechanisms (zip-slip guard, atomic dir swap, the lock
primitive) are exercised in their own widget test suites under
cg/*/tests/. Here we test the CLI glue: that the re-exports are wired, and
that library_lock applies the poll/timeout + reentrancy policy correctly.
"""

import io
import os
import threading
import time
import zipfile

import pytest

from cartograph.safefs import (
    safe_extractall,
    staged_dir,
    atomic_swap_dir,
    library_lock,
    LockTimeout,
    UnsafeArchiveError,
)


# --- re-exports are wired to the widgets ----------------------------------

def test_safe_extractall_reexport_blocks_traversal(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", "x")
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(UnsafeArchiveError):
            safe_extractall(zf, str(tmp_path / "out"))


def test_staged_dir_reexport_swaps_in(tmp_path):
    dest = tmp_path / "w"
    dest.mkdir()
    (dest / "old").write_text("old")
    with staged_dir(str(dest)) as tmp:
        with open(os.path.join(tmp, "new"), "w") as f:
            f.write("new")
    assert (dest / "new").exists() and not (dest / "old").exists()


def test_atomic_swap_dir_reexport(tmp_path):
    new = tmp_path / ".cg-new-x"
    new.mkdir()
    (new / "f").write_text("v")
    atomic_swap_dir(str(new), str(tmp_path / "dest"))
    assert (tmp_path / "dest" / "f").read_text() == "v"


# --- library_lock policy --------------------------------------------------

def test_library_lock_creates_lockfile_and_runs_body(tmp_path):
    ran = []
    with library_lock(str(tmp_path), timeout=2):
        ran.append(True)
        assert os.path.exists(os.path.join(str(tmp_path), ".cartograph.lock"))
    assert ran == [True]


def test_library_lock_reentrant_same_thread(tmp_path):
    d = str(tmp_path)
    with library_lock(d, timeout=2):
        with library_lock(d, timeout=2):  # must not self-deadlock
            pass


def test_library_lock_serializes_threads(tmp_path):
    d = str(tmp_path)
    order = []

    def worker(tag, hold):
        with library_lock(d, timeout=5):
            order.append(f"{tag}-in")
            time.sleep(hold)
            order.append(f"{tag}-out")

    t1 = threading.Thread(target=worker, args=("a", 0.3))
    t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(target=worker, args=("b", 0.0))
    t2.start()
    t1.join()
    t2.join()
    assert order == ["a-in", "a-out", "b-in", "b-out"]


def test_library_lock_times_out_when_held_by_another_process(tmp_path):
    """A separate process holds the library lock; a short timeout must raise
    LockTimeout instead of hanging."""
    import subprocess
    import sys
    import textwrap

    d = str(tmp_path)
    holder = textwrap.dedent(f"""
        import sys, time
        from cartograph.safefs import library_lock
        with library_lock({d!r}, timeout=5):
            print("HELD", flush=True)
            time.sleep(3)
    """)
    proc = subprocess.Popen([sys.executable, "-c", holder],
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "HELD"
        with pytest.raises(LockTimeout):
            with library_lock(d, timeout=0.5, poll=0.05):
                pass
    finally:
        proc.wait(timeout=10)
