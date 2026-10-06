"""Bridge script the Blender engine runs inside Blender's embedded Python.

    blender -b --factory-startup --python-exit-code 1 --python blender_runner.py \
        -- <mode> <widget_root> <tools_dir> [args...]

Modes:
    info     print one CARTOGRAPH_INFO line (JSON) describing the interpreter
    pip      run pip with Blender's own interpreter (installs test tools)
    test     run pytest with [args...]
    example  run the example script at args[0] as __main__

Runs pip inside Blender (instead of the interpreter sys.executable names)
because some distro builds report a different Python than the one they embed;
tools installed this way always match the interpreter that imports them.
Blender exits with the code passed to sys.exit, and 1 on an uncaught exception
(--python-exit-code 1), so the engine reads results from the exit status.
"""
import json
import os
import runpy
import sys


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    mode, root, tools = argv[0], argv[1], argv[2]
    rest = argv[3:]

    if mode == "info":
        import bpy
        try:
            import pip  # noqa: F401
            has_pip = True
        except ImportError:
            has_pip = False
        info = {
            "python": "%d.%d.%d" % sys.version_info[:3],
            "blender": "%d.%d.%d" % tuple(bpy.app.version),
            "pip": has_pip,
        }
        sys.stdout.write("CARTOGRAPH_INFO " + json.dumps(info) + "\n")
        sys.exit(0)

    if mode == "pip":
        sys.argv = ["pip"] + rest
        runpy.run_module("pip", run_name="__main__", alter_sys=True)
        sys.exit(0)

    if tools:
        sys.path.insert(0, tools)
    sys.path.insert(0, root)
    os.chdir(root)

    if mode == "test":
        import pytest
        sys.exit(pytest.main(rest))

    if mode == "example":
        runpy.run_path(rest[0], run_name="__main__")
        sys.exit(0)

    sys.stderr.write("unknown mode: %s\n" % mode)
    sys.exit(2)


main()
