"""Filesystem safety glue for library-mutating operations.

Thin wrappers over three widgets that own the actual mechanisms:

* ``cg.infra_interprocess_lock_python`` - cross-process advisory lock
* ``cg.universal_atomic_dir_swap_python`` - crash-safe directory replace
* ``cg.universal_safe_archive_extract_python`` - zip-slip-guarded extraction

This module owns only CLI *policy*: where the library lock file lives, and the
poll/timeout wait loop. The wait loop can't live in the lock widget - a busy
``sleep`` is blocked in widget ``src`` by the validator - so the widget exposes
non-blocking ``file_lock(blocking=False)`` and the timed retry lives here.
"""

import os
import time
from contextlib import contextmanager

from cg.infra_interprocess_lock_python.src.interprocess_lock import (
    file_lock as _file_lock,
    LockBusy as _LockBusy,
)
from cg.universal_atomic_dir_swap_python.src.atomic_dir_swap import (
    staged_dir,
    atomic_swap_dir,
)
from cg.universal_safe_archive_extract_python.src.safe_archive_extract import (
    safe_extractall,
    safe_extract_zip,
    UnsafeArchiveError,
)

__all__ = [
    "safe_extractall",
    "safe_extract_zip",
    "UnsafeArchiveError",
    "staged_dir",
    "atomic_swap_dir",
    "library_lock",
    "LockTimeout",
]

LOCK_FILENAME = ".cartograph.lock"


class LockTimeout(RuntimeError):
    """Raised when the library lock can't be acquired within the timeout."""


@contextmanager
def library_lock(lock_dir, timeout=30.0, poll=0.1):
    """Exclusive cross-process lock over a library directory.

    Serializes library-mutating operations (checkin / sync / delete / import)
    against other cartograph processes. Reentrant within a single thread (the
    underlying widget keys reentrancy by lock path). Raises ``LockTimeout`` if
    another holder keeps it past ``timeout``.
    """
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, LOCK_FILENAME)

    # Acquire with a timed retry, kept separate from the body so an exception
    # raised inside the locked section is never mistaken for contention.
    deadline = time.monotonic() + timeout
    cm = None
    while cm is None:
        attempt = _file_lock(lock_path, blocking=False)
        try:
            attempt.__enter__()
            cm = attempt
        except _LockBusy:
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"Could not acquire the library lock within {timeout:.0f}s "
                    f"({lock_path}). Another cartograph process may be running; "
                    f"retry once it finishes."
                )
            time.sleep(poll)
    try:
        yield
    finally:
        cm.__exit__(None, None, None)
