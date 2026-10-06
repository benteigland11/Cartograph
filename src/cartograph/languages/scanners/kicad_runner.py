"""Bridge script the KiCad engine runs with KiCad's own Python.

    <kicad python> kicad_runner.py <mode> <widget_root> <deps_dir> <tools_dir> [args...]

Modes:
    test     run pytest with [args...]
    example  run the example script at args[0] as __main__

Sets sys.path explicitly instead of relying on PYTHONPATH: KiCad's Windows
interpreter ignores PYTHONPATH and adds the user's per-version "3rdparty"
site-packages, so the runner drops every entry outside the interpreter's own
prefix and puts the widget root, the declared-deps dir and the test-tool dir
first. Exits with pytest's code or 1 on an uncaught example exception.
"""
import os
import runpy
import sys


def _own_paths():
    prefixes = {os.path.normcase(os.path.realpath(p))
                for p in (sys.prefix, sys.base_prefix, sys.exec_prefix) if p}
    kept = []
    for entry in sys.path:
        if not entry:
            continue
        real = os.path.normcase(os.path.realpath(entry))
        if any(real == p or real.startswith(p + os.sep) for p in prefixes):
            kept.append(entry)
    return kept


def main():
    mode, root, deps, tools = sys.argv[1:5]
    rest = sys.argv[5:]
    sys.path[:] = [p for p in (root, deps, tools) if p] + _own_paths()
    os.chdir(root)

    if mode == "test":
        import pytest
        sys.exit(pytest.main(rest))

    if mode == "example":
        sys.argv = [rest[0]]
        runpy.run_path(rest[0], run_name="__main__")
        sys.exit(0)

    sys.stderr.write("unknown mode: %s\n" % mode)
    sys.exit(2)


main()
