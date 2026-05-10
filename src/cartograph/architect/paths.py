"""Locate the project's architect.py file."""

import os
from typing import Optional


ARCHITECT_FILENAME = "architect.py"


def resolve_architect_path(
    explicit: Optional[str] = None,
    *,
    start_dir: Optional[str] = None,
) -> str:
    """Return the absolute path to the project's architect.py.

    If explicit is given, it is normalized and returned (no existence
    check - callers handle that).

    Otherwise the search begins at start_dir (default: current working
    directory) and looks only at that directory. Walking parent
    directories is intentionally not done: an architecture file is a
    per-project artifact and should live at the project root the user
    invokes Cartograph from.
    """
    if explicit:
        return os.path.abspath(explicit)
    base = start_dir or os.getcwd()
    return os.path.join(os.path.abspath(base), ARCHITECT_FILENAME)
