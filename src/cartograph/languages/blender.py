"""Blender (bpy) language engine.

Validates reusable Blender Python - geometry generators, bmesh operations,
node/material builders, export helpers - inside headless Blender
(`blender -b --factory-startup`), never the UI and never a GPU render.

Blender widgets are Python, but they only run in Blender's embedded
interpreter with `bpy`, so tests, installs and examples all differ from the
Python engine; only contamination scanning is shared (the Python AST scanner,
plus Blender-specific checks on top).

Layout
------
    widget_root/
      src/__init__.py
      src/<name>.py              the reusable module (imports bpy/bmesh/...)
      tests/conftest.py          resets bpy.data between tests
      tests/test_<name>.py       pytest, run inside Blender
      examples/example_usage.py  runs inside headless Blender, exits cleanly

Tests run with pytest + pytest-cov at an 80% floor. Those tools are installed
once per Blender Python version into the Cartograph data dir by pip running
*inside* Blender (scanners/blender_runner.py), so they always match the
interpreter that imports them and nothing is written into Blender itself.

v1 scope: Blender 4.2 LTS or newer; widgets may import only the standard
library and what Blender bundles (bpy, bmesh, mathutils, numpy, ...). Declared
pip dependencies are refused until v2.
"""

import ast
import glob
import json
import os
import re
import shutil
import tempfile

from . import python as _python
from .base import LanguageEngine, log

_COVERAGE_THRESHOLD = 80
_MIN_BLENDER = (4, 2)
_TEST_TOOLS = ["pytest", "pytest-cov"]

# Importable inside every supported Blender without installing anything.
_BUNDLED_MODULES = [
    "bpy", "bmesh", "mathutils", "bpy_extras", "bl_math", "gpu", "gpu_extras",
    "idprop", "aud", "freestyle", "imbuf", "bpy_types", "addon_utils",
    "rna_prop_ui", "numpy",
]

# Operators that read or write .blend files; a literal path in src/ ties the
# widget to one machine's files.
_FILE_OPS = {"wm.open_mainfile", "wm.save_mainfile", "wm.save_as_mainfile",
             "wm.append", "wm.link"}
_PATH_KWARGS = {"filepath", "directory", "filename"}

_RUNNER = os.path.join(os.path.dirname(__file__), "scanners", "blender_runner.py")

_SRC_INIT = "# Package marker - add explicit exports here once the public API is stable.\n"

_SRC_TEMPLATE = '''\
"""{name}.

[TODO] Replace with the widget's real API. Work through the data API
(bpy.data, bmesh) rather than bpy.ops - operators depend on UI context.
"""
import bpy


def {module}(name="Widget", size=1.0):
    """Create a square plane mesh object of the given size and return it."""
    half = size / 2
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
'''

_CONFTEST_TEMPLATE = '''\
"""Every test starts from an empty Blender scene."""
import bpy
import pytest


@pytest.fixture(autouse=True)
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield
'''

_TEST_TEMPLATE = '''\
from src.{module} import {module}


def test_creates_one_quad_of_the_requested_size():
    # [TODO] Replace with assertions about the widget's real behavior
    obj = {module}(size=2.0)
    assert len(obj.data.polygons) == 1
    assert tuple(round(d, 6) for d in obj.dimensions) == (2.0, 2.0, 0.0)
'''

_EXAMPLE_TEMPLATE = '''\
"""
Example usage of {name}.

Runs inside headless Blender (blender -b) and must exit cleanly with no user
input, no network calls and no GPU rendering. Use fake/hardcoded parameters.
"""
from src.{module} import {module}

# [TODO] Replace with a realistic call using fake data
obj = {module}(size=2.0)
print(f"Created {{obj.name}} with {{len(obj.data.vertices)}} vertices")
'''


def _dotted(node):
    """'bpy.ops.mesh.primitive_cube_add' for an attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class BlenderEngine(LanguageEngine):
    name = "blender"
    validation_version = 1
    file_ext = "py"
    aliases = ["bpy"]
    toolchain = {"blender": "Install Blender 4.2 LTS or newer - blender.org "
                            "(validation runs it headless with -b)"}
    supported = False
    # blender.exe is a real executable; no cmd.exe in between.
    windows_shell = False

    def __init__(self):
        super().__init__()
        self._tools_dir = None

    # ---- toolchain ---------------------------------------------------------

    def runtime_version(self):
        try:
            res = self._run(["blender", "--version"], cwd=".", timeout=60,
                            env=self._blender_env())
        except Exception:
            return None
        for line in (res.stdout or "").splitlines():
            m = re.match(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", line.strip())
            if m:
                return f"blender {m.group(1)}"
        return None

    def check_available(self):
        ok, msg = super().check_available()
        if not ok:
            return ok, msg
        version = self._version_tuple()
        if version is None:
            return False, "blender is on PATH but `blender --version` did not report a version"
        if version < _MIN_BLENDER:
            return False, (f"Blender engine requires Blender {_MIN_BLENDER[0]}.{_MIN_BLENDER[1]} "
                           f"LTS or newer; found {'.'.join(map(str, version))}")
        return True, ""

    def _version_tuple(self):
        v = self.runtime_version()
        if not v:
            return None
        return tuple(int(p) for p in v.split()[1].split("."))

    # ---- scaffold ----------------------------------------------------------

    def scaffold(self, target_dir, module_name, display_name, **_):
        def _w(rel, content):
            full = os.path.join(target_dir, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

        _w(os.path.join("src", "__init__.py"), _SRC_INIT)
        _w(os.path.join("src", f"{module_name}.py"),
           _SRC_TEMPLATE.format(module=module_name, name=display_name))
        _w(os.path.join("tests", "conftest.py"), _CONFTEST_TEMPLATE)
        _w(os.path.join("tests", f"test_{module_name}.py"),
           _TEST_TEMPLATE.format(module=module_name))
        _w(os.path.join("examples", "example_usage.py"),
           _EXAMPLE_TEMPLATE.format(module=module_name, name=display_name))

    def find_test_files(self, path):
        return glob.glob(os.path.join(path, "tests", "**", "test_*.py"), recursive=True)

    def example_filename(self, path=""):
        return "example_usage.py"

    def required_files(self, path):
        if os.path.isfile(os.path.join(path, "src", "__init__.py")):
            return []
        return [("src/__init__.py",
                 "src/__init__.py is missing - add an empty one so `from src.<module>` imports")]

    def src_import_pattern(self):
        return r'from src\.|import src\.'

    # ---- validation --------------------------------------------------------

    def validate_widget(self, path, dependencies):
        errors = []
        src_files = _python._py_files(path, "src")
        if not [f for f in src_files if os.path.basename(f) != "__init__.py"]:
            errors.append("src/ contains no modules - add at least one .py file")

        py = _python.PythonEngine()
        for fpath in src_files:
            for lineno in py._find_print_calls(fpath):
                rel = os.path.relpath(fpath, path)
                errors.append(f"print() in {rel}:{lineno} - remove debug output from src/")

        if dependencies:
            errors.append(
                "Blender widgets cannot declare dependencies yet (v1): import only the "
                "standard library and modules Blender bundles ("
                + ", ".join(_BUNDLED_MODULES) + "). Remove: " + ", ".join(map(str, dependencies))
            )

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def scan_contamination(self, path, widget):
        # The Python scanner treats declared deps as importable; Blender's
        # bundled modules are importable without being declared.
        scan_widget = dict(widget)
        scan_widget["dependencies"] = list(widget.get("dependencies", [])) + _BUNDLED_MODULES
        result = _python.PythonEngine().scan_contamination(path, scan_widget)
        blocks, warnings = list(result["blocks"]), list(result["warnings"])

        for fpath in _python._py_files(path, "src"):
            rel = os.path.relpath(fpath, path)
            try:
                with open(fpath, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except (OSError, SyntaxError):
                continue  # the Python scanner already blocked an unparsable src file
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                dotted = _dotted(node.func)
                if not dotted or not dotted.startswith("bpy.ops."):
                    continue
                op = dotted[len("bpy.ops."):]
                literal_path = any(
                    kw.arg in _PATH_KWARGS and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                    for kw in node.keywords
                )
                if op in _FILE_OPS and literal_path:
                    blocks.append(
                        f"bpy.ops.{op} with a literal path in {rel}:{node.lineno} - "
                        f"take the path as a parameter")
                else:
                    warnings.append(
                        f"bpy.ops.{op} in {rel}:{node.lineno} - operators depend on UI "
                        f"context and break headless; prefer the data API (bpy.data, bmesh)")
        return {"blocks": blocks, "warnings": warnings}

    # ---- dependencies ------------------------------------------------------

    def install_deps(self, path, dependencies):
        """Make pytest + pytest-cov importable by Blender's Python.

        Installed once per Blender Python version into the Cartograph data
        dir and reused; widget dependencies are refused in validate_widget."""
        info = self._interpreter_info()
        tools = os.path.join(self._tools_root(), f"py{'.'.join(info['python'].split('.')[:2])}")
        if all(os.path.isdir(os.path.join(tools, m)) for m in ("pytest", "pytest_cov")):
            self._tools_dir = tools
            return
        if not info.get("pip"):
            raise RuntimeError(
                "Blender's Python has no pip, so the test tools (pytest, pytest-cov) cannot be "
                f"installed. Install them for Python {info['python']} into {tools} and re-run.")

        staging = tempfile.mkdtemp(prefix="tools-", dir=self._tools_root())
        res = self._blender(["pip", "", "", "install", "-q", "--no-cache-dir",
                             "--disable-pip-version-check", "--target", staging] + _TEST_TOOLS,
                            cwd=path, timeout=600)
        if res.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError(
                "Could not install Blender test tools (pytest, pytest-cov) into "
                f"{tools}. They are fetched from PyPI once per Blender Python version.\n"
                + self._output(res)[-2000:])
        # Another validation may have finished the same install meanwhile.
        if os.path.isdir(tools):
            shutil.rmtree(staging, ignore_errors=True)
        else:
            os.replace(staging, tools)
        log.debug("Installed Blender test tools for Python %s at %s", info["python"], tools)
        self._tools_dir = tools

    # ---- tests + example ---------------------------------------------------

    def run_tests(self, path):
        if not self.find_test_files(path):
            return self._fail("No test files found in tests/ (test_*.py)")
        res = self._blender(
            ["test", path, self._tools_dir or "",
             "tests", "-p", "no:cacheprovider", "--tb=short",
             "--cov=src", f"--cov-fail-under={_COVERAGE_THRESHOLD}",
             "--cov-report=term-missing"],
            cwd=path, timeout=600)
        if res.returncode != 0:
            return self._fail(self._output(res))
        return self._ok()

    def run_example(self, path):
        ex = os.path.join(path, "examples", self.example_filename())
        if not os.path.isfile(ex):
            return self._fail("examples/example_usage.py not found")
        res = self._blender(["example", path, self._tools_dir or "", ex], cwd=path, timeout=300)
        if res.returncode != 0:
            return self._fail(self._output(res))
        return self._ok()

    def cleanup(self, path):
        try:
            from cg.universal_build_artifact_ignore_python.src.build_artifact_ignore import (
                excludes_for,
            )
            artifacts = excludes_for(language="python")
        except ImportError:
            artifacts = frozenset({"__pycache__", ".pytest_cache", ".coverage"})
        # Blender widgets are Python source: Python's artifacts are theirs.
        for root, dirs, files in os.walk(path):
            for d in [d for d in dirs if d in artifacts]:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            dirs[:] = [d for d in dirs if d not in artifacts]
            for f in files:
                if f in artifacts or f.startswith(".coverage."):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass

    # ---- private -----------------------------------------------------------

    def _blender(self, runner_args, cwd, timeout):
        cmd = ["blender", "-b", "--factory-startup", "--python-exit-code", "1",
               "--python", _RUNNER, "--"] + runner_args
        return self._run(cmd, cwd=cwd, timeout=timeout, env=self._blender_env())

    def _interpreter_info(self):
        res = self._blender(["info", ".", ""], cwd=os.getcwd(), timeout=120)
        for line in (res.stdout or "").splitlines():
            if line.startswith("CARTOGRAPH_INFO "):
                return json.loads(line[len("CARTOGRAPH_INFO "):])
        raise RuntimeError("Could not query Blender's Python interpreter:\n"
                           + self._output(res)[-2000:])

    @staticmethod
    def _tools_root():
        from ..engine import _user_data_dir
        root = os.path.join(_user_data_dir(), "blender-test-tools")
        os.makedirs(root, exist_ok=True)
        return root

    @staticmethod
    def _output(res):
        return ((res.stdout or "") + (res.stderr or "")).strip()

    @staticmethod
    def _blender_env():
        """Keep Blender off the user's config, scripts and add-ons, and keep
        user-site packages out of the interpreter, so validation sees a
        factory Blender and works where $HOME is read-only."""
        env = os.environ.copy()
        home = os.path.join(tempfile.gettempdir(), "cartograph-blender-user")
        os.makedirs(home, exist_ok=True)
        env["BLENDER_USER_RESOURCES"] = home
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env
