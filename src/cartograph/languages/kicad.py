"""KiCad language engine.

Validates reusable KiCad automation - board, footprint and symbol
generators, netlist and fabrication helpers - as Python run under the
interpreter KiCad ships (the one that can `import pcbnew`), with `kicad-cli`
available for ERC/DRC, netlist and export checks. Widgets may also bundle
native KiCad files under src/ (symbol libraries, footprint libraries,
schematics, boards); those are validated by kicad-cli itself.

KiCad widgets are Python, but `pcbnew` only imports in KiCad's own
interpreter, so tests, installs and examples differ from the Python engine;
contamination scanning is shared (the Python AST scanner, plus KiCad-specific
checks on top).

Layout
------
    widget_root/
      src/__init__.py
      src/<name>.py              the reusable module (imports pcbnew, ...)
      src/<anything>.kicad_sym   optional native files, checked by kicad-cli
      tests/test_<name>.py       pytest, run under KiCad's Python
      examples/example_usage.py  runs under KiCad's Python, exits cleanly

Tests run with pytest + pytest-cov at an 80% floor. Those tools are installed
once per KiCad Python version into the Cartograph data dir; declared widget
dependencies are installed per run into a temp directory. Nothing is ever
written into KiCad's or the system's site-packages.

Native files in src/:
    *.kicad_sym          must load: kicad-cli sym upgrade into a temp file
    *.pretty/ (*.kicad_mod)  must load: kicad-cli fp upgrade into a temp dir
    *.kicad_sch          ERC must report no errors
    *.kicad_pcb          DRC must report no errors

v1 scope: KiCad 10 or newer; the scripting surface is the SWIG `pcbnew`
module plus kicad-cli. The IPC API (kipy) needs a running KiCad GUI and is
blocked.
"""

import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import python as _python
from .base import LanguageEngine, _override_for, log

_COVERAGE_THRESHOLD = 80
_MIN_KICAD = (10, 0)
_TEST_TOOLS = ["pytest", "pytest-cov"]

# Importable in KiCad's interpreter without installing anything.
_BUNDLED_MODULES = ["pcbnew"]

# pcbnew calls that only mean something inside the running PCB editor.
_GUI_CALLS = {
    "pcbnew.GetBoard": "returns the board open in the PCB editor (None headless) - "
                       "take a board parameter or load one with pcbnew.LoadBoard(path)",
    "pcbnew.Refresh": "redraws the PCB editor - there is no editor headless",
    "pcbnew.UpdateUserInterface": "updates the PCB editor UI - there is no editor headless",
}
# Modules that need a GUI or a running KiCad instance.
_GUI_MODULES = {
    "wx": "wxPython is the KiCad GUI toolkit",
    "kipy": "the KiCad IPC API needs a running KiCad GUI",
    "kicad": "the KiCad IPC API needs a running KiCad GUI",
}

# A 3D model or library reference pinned to one machine.
_ABS_MODEL_RE = re.compile(r'\(model\s+"((?:[A-Za-z]:[\\/]|/|~)[^"]*)"')

# One line: cmd.exe would cut a multi-line -c at the first newline.
_PROBE = ("import sys, json, importlib.util as u; import pcbnew; "
          "v = pcbnew.Version() if hasattr(pcbnew, 'Version') else pcbnew.GetBuildVersion(); "
          "print('CARTOGRAPH_INFO ' + json.dumps({'python': '%d.%d.%d' % sys.version_info[:3], "
          "'kicad': str(v), 'pip': u.find_spec('pip') is not None}))")

_SRC_INIT = "# Package marker - add explicit exports here once the public API is stable.\n"

_SRC_TEMPLATE = '''\
"""{name}.

[TODO] Replace with the widget's real API.

Coordinate frame: KiCad board coordinates - origin at the board's top-left
reference point, +X right, +Y down (KiCad's screen convention), lengths in
millimetres at this API and nanometres inside pcbnew (pcbnew.FromMM).
"""
import pcbnew


def {module}(width_mm=20.0, height_mm=10.0):
    """Return a new board with a rectangular Edge.Cuts outline.

    width_mm, height_mm: outline size in millimetres (> 0).
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("outline width and height must be positive")
    board = pcbnew.BOARD()
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetLayer(pcbnew.Edge_Cuts)
    outline.SetStart(pcbnew.VECTOR2I(0, 0))
    outline.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(width_mm), pcbnew.FromMM(height_mm)))
    board.Add(outline)
    return board
'''

_TEST_TEMPLATE = '''\
import json
import shutil
import subprocess

import pcbnew
import pytest

from src.{module} import {module}


def test_outline_has_the_requested_size():
    # [TODO] Replace with assertions about the widget's real behavior
    board = {module}(width_mm=30.0, height_mm=15.0)
    [outline] = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    size = outline.GetEnd() - outline.GetStart()
    assert (pcbnew.ToMM(size.x), pcbnew.ToMM(size.y)) == (30.0, 15.0)


def test_saved_board_passes_drc(tmp_path):
    path = tmp_path / "outline.kicad_pcb"
    pcbnew.SaveBoard(str(path), {module}())
    report = tmp_path / "drc.json"
    subprocess.run([shutil.which("kicad-cli"), "pcb", "drc", "--format", "json",
                    "--severity-error", "-o", str(report), str(path)], check=True)
    assert json.loads(report.read_text())["violations"] == []


def test_rejects_non_positive_size():
    with pytest.raises(ValueError):
        {module}(width_mm=0)
'''

_EXAMPLE_TEMPLATE = '''\
"""
Example usage of {name}.

Runs under KiCad's Python (the interpreter with pcbnew) and must exit cleanly
with no user input, no network calls and no GUI. Use fake parameters and
write only to a temp directory.
"""
import os
import tempfile

import pcbnew

from src.{module} import {module}

# [TODO] Replace with a realistic call using fake data
board = {module}(width_mm=50.0, height_mm=30.0)
out = os.path.join(tempfile.mkdtemp(), "example.kicad_pcb")
pcbnew.SaveBoard(out, board)
print(f"Saved {{out}} ({{os.path.getsize(out)}} bytes)")
'''


def _dotted(node):
    """'pcbnew.GetBoard' for an attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _native_files(path):
    src = os.path.join(path, "src")
    found = {"sym": [], "pretty": [], "sch": [], "pcb": []}
    for root, dirs, files in os.walk(src):
        for d in dirs:
            if d.endswith(".pretty"):
                found["pretty"].append(os.path.join(root, d))
        for f in files:
            for kind in ("sym", "sch", "pcb"):
                if f.endswith(f".kicad_{kind}"):
                    found[kind].append(os.path.join(root, f))
    return {k: sorted(v) for k, v in found.items()}


class KicadEngine(LanguageEngine):
    name = "kicad"
    validation_version = 1
    file_ext = "py"
    aliases = ["pcbnew"]
    toolchain = {"kicad-cli": "Install KiCad 10 or newer - kicad.org "
                              "(validation uses kicad-cli and KiCad's bundled Python)"}
    # Native KiCad files a widget may carry; also whitelists them for publish.
    manifest_patterns = ["src/*.kicad_sym", "src/*.kicad_mod", "src/*.kicad_sch",
                         "src/*.kicad_pcb", "src/*.kicad_pro", "src/*.kicad_dru"]
    supported = False
    # kicad-cli and KiCad's python are real executables; no cmd.exe in between.
    windows_shell = False

    def __init__(self):
        super().__init__()
        self._tools_dir = None
        self._deps_dir = None
        self._python = None
        self._info = None

    # ---- toolchain ---------------------------------------------------------

    def runtime_version(self):
        try:
            res = self._run(["kicad-cli", "version"], cwd=".", timeout=60, env=self._kicad_env())
        except Exception:
            return None
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", res.stdout or "")
        return f"kicad {m.group(1)}" if m else None

    def check_available(self):
        ok, msg = super().check_available()
        if not ok:
            return ok, msg
        version = self._version_tuple()
        if version is None:
            return False, "kicad-cli is on PATH but `kicad-cli version` did not report a version"
        if version < _MIN_KICAD:
            return False, (f"KiCad engine requires KiCad {_MIN_KICAD[0]} or newer; "
                           f"found {'.'.join(map(str, version))}")
        if self._kicad_python() is None:
            return False, ("No Python interpreter that can `import pcbnew` was found next to "
                           "kicad-cli or on PATH. Point Cartograph at KiCad's Python with "
                           "`cartograph config set paths.kicad-python <path>`")
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

        errors.extend(self._check_dep_pinning(dependencies))
        errors.extend(self._check_native_files(path))

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def _check_native_files(self, path):
        """Every bundled KiCad file must load (libraries) or pass ERC/DRC."""
        native = _native_files(path)
        if not any(native.values()):
            return []
        errors = []
        work = tempfile.mkdtemp(prefix="cg-kicad-native-")
        try:
            for f in native["sym"]:
                res = self._cli(["sym", "upgrade", "--force", "-o",
                                 os.path.join(work, os.path.basename(f)), f], cwd=path)
                if res.returncode != 0:
                    errors.append(f"{os.path.relpath(f, path)} does not load in KiCad:\n"
                                  + self._output(res)[-1500:])
            for d in native["pretty"]:
                res = self._cli(["fp", "upgrade", "--force", "-o",
                                 os.path.join(work, os.path.basename(d)), d], cwd=path)
                if res.returncode != 0:
                    errors.append(f"{os.path.relpath(d, path)} does not load in KiCad:\n"
                                  + self._output(res)[-1500:])
            for kind, check in (("sch", "erc"), ("pcb", "drc")):
                for f in native[kind]:
                    errors.extend(self._rule_check(path, kind, check, f, work))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return errors

    def _rule_check(self, path, kind, check, fpath, work):
        rel = os.path.relpath(fpath, path)
        report = os.path.join(work, os.path.basename(fpath) + f".{check}.json")
        res = self._cli([kind, check, "--format", "json", "--severity-error",
                         "-o", report, fpath], cwd=path)
        try:
            with open(report, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return [f"{rel}: kicad-cli {kind} {check} produced no report:\n"
                    + self._output(res)[-1500:]]
        found = list(data.get("violations", []))
        for sheet in data.get("sheets", []):
            found.extend(sheet.get("violations", []))
        found.extend(data.get("unconnected_items", []))
        if not found:
            return []
        lines = [f"  - {v.get('type', '?')}: {v.get('description', '')}" for v in found[:20]]
        more = f"\n  ... and {len(found) - 20} more" if len(found) > 20 else ""
        return [f"{rel}: {check.upper()} reports {len(found)} error(s):\n"
                + "\n".join(lines) + more]

    def scan_contamination(self, path, widget):
        # The Python scanner treats declared deps as importable; pcbnew is
        # importable in KiCad's interpreter without being declared.
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
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                             else [node.module or ""])
                    for mod in names:
                        top = mod.split(".")[0]
                        if top in _GUI_MODULES:
                            blocks.append(f"import {mod} in {rel}:{node.lineno} - "
                                          f"{_GUI_MODULES[top]}; validation runs headless")
                elif isinstance(node, ast.Call):
                    dotted = _dotted(node.func)
                    if dotted in _GUI_CALLS:
                        blocks.append(f"{dotted}() in {rel}:{node.lineno} - {_GUI_CALLS[dotted]}")
                elif isinstance(node, ast.ClassDef):
                    if any(_dotted(b) == "pcbnew.ActionPlugin" for b in node.bases):
                        warnings.append(
                            f"pcbnew.ActionPlugin subclass {node.name} in {rel}:{node.lineno} - "
                            "Run() needs the PCB editor; keep the logic in plain functions "
                            "that take a board so it can be tested headless")

        for root, _dirs, files in os.walk(os.path.join(path, "src")):
            for f in files:
                if not f.endswith((".kicad_mod", ".kicad_sym", ".kicad_sch", ".kicad_pcb")):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, encoding="utf-8") as fh:
                        lines = fh.read().splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for lineno, line in enumerate(lines, start=1):
                    m = _ABS_MODEL_RE.search(line)
                    if m:
                        blocks.append(
                            f"Absolute 3D model path {m.group(1)!r} in "
                            f"{os.path.relpath(fpath, path)}:{lineno} - use a KiCad path "
                            "variable such as ${KICAD10_3DMODEL_DIR} or a path relative "
                            "to the library")
        return {"blocks": blocks, "warnings": warnings}

    # ---- dependencies ------------------------------------------------------

    def install_deps(self, path, dependencies):
        """Make pytest + pytest-cov (and declared deps) importable by KiCad's Python.

        Test tools are installed once per KiCad Python version into the
        Cartograph data dir and reused; declared dependencies go into a
        per-run temp dir removed by cleanup()."""
        info = self._interpreter_info()
        pyver = ".".join(info["python"].split(".")[:2])
        tools = os.path.join(self._tools_root(), f"py{pyver}")
        if not all(os.path.isdir(os.path.join(tools, m)) for m in ("pytest", "pytest_cov")):
            staging = tempfile.mkdtemp(prefix="tools-", dir=self._tools_root())
            res = self._pip_target(info, staging, _TEST_TOOLS, cwd=path)
            if res.returncode != 0:
                shutil.rmtree(staging, ignore_errors=True)
                raise RuntimeError(
                    "Could not install KiCad test tools (pytest, pytest-cov) into "
                    f"{tools}. They are fetched from PyPI once per KiCad Python version.\n"
                    + self._output(res)[-2000:])
            # Another validation may have finished the same install meanwhile.
            if os.path.isdir(tools):
                shutil.rmtree(staging, ignore_errors=True)
            else:
                os.replace(staging, tools)
            log.debug("Installed KiCad test tools for Python %s at %s", info["python"], tools)
        self._tools_dir = tools

        self._deps_dir = None
        deps = [str(d) for d in dependencies or []]
        if deps:
            target = tempfile.mkdtemp(prefix="cg-kicad-deps-")
            res = self._pip_target(info, target, deps, cwd=path)
            if res.returncode != 0:
                shutil.rmtree(target, ignore_errors=True)
                raise RuntimeError("Could not install widget dependencies for KiCad's Python "
                                   f"({', '.join(deps)}):\n" + self._output(res)[-2000:])
            self._deps_dir = target

    def _pip_target(self, info, target, packages, cwd):
        """pip install --target with KiCad's own pip, else the CLI's pip
        pinned to KiCad's Python version (binary wheels only)."""
        base = ["install", "-q", "--no-cache-dir", "--disable-pip-version-check",
                "--target", target]
        if info.get("pip"):
            cmd = [self._kicad_python(), "-m", "pip"] + base + packages
        else:
            pyver = ".".join(info["python"].split(".")[:2])
            cmd = [sys.executable, "-m", "pip"] + base + [
                "--python-version", pyver, "--only-binary=:all:", "--implementation", "cp",
            ] + packages
        return self._run(cmd, cwd=cwd, timeout=900, env=self._kicad_env())

    # ---- tests + example ---------------------------------------------------

    def run_tests(self, path):
        if not self.find_test_files(path):
            return self._fail("No test files found in tests/ (test_*.py)")
        res = self._run(
            [self._kicad_python(), "-m", "pytest", "tests", "-p", "no:cacheprovider",
             "--tb=short", "--cov=src", f"--cov-fail-under={_COVERAGE_THRESHOLD}",
             "--cov-report=term-missing"],
            cwd=path, timeout=900, env=self._kicad_env(path))
        if res.returncode != 0:
            return self._fail(self._output(res))
        return self._ok()

    def run_example(self, path):
        ex = os.path.join(path, "examples", self.example_filename())
        if not os.path.isfile(ex):
            return self._fail("examples/example_usage.py not found")
        res = self._run([self._kicad_python(), ex], cwd=path, timeout=300,
                        env=self._kicad_env(path))
        if res.returncode != 0:
            return self._fail(self._output(res))
        return self._ok()

    def cleanup(self, path):
        if self._deps_dir:
            shutil.rmtree(self._deps_dir, ignore_errors=True)
            self._deps_dir = None
        try:
            from cg.universal_build_artifact_ignore_python.src.build_artifact_ignore import (
                excludes_for,
            )
            artifacts = excludes_for(language="python")
        except ImportError:
            artifacts = frozenset({"__pycache__", ".pytest_cache", ".coverage"})
        # KiCad widgets are Python source: Python's artifacts are theirs, plus
        # the lock/backup files KiCad drops next to files it opens.
        for root, dirs, files in os.walk(path):
            for d in [d for d in dirs if d in artifacts or d.endswith("-backups")]:
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            dirs[:] = [d for d in dirs if d not in artifacts and not d.endswith("-backups")]
            for f in files:
                if (f in artifacts or f.startswith(".coverage.") or f == "fp-info-cache"
                        or (f.startswith("~") and f.endswith(".lck"))):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass

    # ---- private -----------------------------------------------------------

    def _cli(self, args, cwd):
        return self._run(["kicad-cli"] + args, cwd=cwd, timeout=300, env=self._kicad_env())

    def _kicad_cli_path(self):
        resolved = self.resolved_binary("kicad-cli")
        return resolved.path if resolved else shutil.which("kicad-cli")

    def _python_candidates(self):
        override = _override_for("kicad-python")
        if override:
            return [override]
        found = []
        cli = self._kicad_cli_path()
        if cli:
            real = os.path.realpath(cli)
            bindir = os.path.dirname(real)
            # Windows: python.exe sits next to kicad-cli.exe in KiCad's bin dir.
            found.append(os.path.join(bindir, "python.exe"))
            # macOS: KiCad.app/Contents/MacOS/kicad-cli -> bundled framework.
            found.append(os.path.join(os.path.dirname(bindir), "Frameworks", "Python.framework",
                                      "Versions", "Current", "bin", "python3"))
        # Linux distro packages install pcbnew into the system interpreter.
        found += ["/usr/bin/python3", shutil.which("python3") or "", sys.executable]
        seen, out = set(), []
        for c in found:
            if c and c not in seen and os.path.isfile(c):
                seen.add(c)
                out.append(c)
        return out

    def _kicad_python(self):
        if self._python:
            return self._python
        for cand in self._python_candidates():
            info = self._probe(cand)
            if info:
                self._python, self._info = cand, info
                return cand
        return None

    def _probe(self, interpreter):
        try:
            res = subprocess.run([interpreter, "-c", _PROBE], capture_output=True, text=True,
                                 timeout=120, env=self._kicad_env())
        except (OSError, subprocess.SubprocessError):
            return None
        for line in (res.stdout or "").splitlines():
            if line.startswith("CARTOGRAPH_INFO "):
                return json.loads(line[len("CARTOGRAPH_INFO "):])
        return None

    def _interpreter_info(self):
        if self._kicad_python() is None:
            raise RuntimeError("No Python interpreter that can `import pcbnew` was found. "
                               "Set `cartograph config set paths.kicad-python <path>` to "
                               "KiCad's bundled Python.")
        return self._info

    @staticmethod
    def _tools_root():
        from ..engine import _user_data_dir
        root = os.path.join(_user_data_dir(), "kicad-test-tools")
        os.makedirs(root, exist_ok=True)
        return root

    @staticmethod
    def _output(res):
        return ((res.stdout or "") + (res.stderr or "")).strip()

    def _kicad_env(self, widget_root=None):
        """A factory KiCad: config in a temp dir, no user-site packages, the
        widget + its deps + test tools on sys.path, kicad-cli on PATH."""
        env = os.environ.copy()
        config = os.path.join(tempfile.gettempdir(), "cartograph-kicad-config")
        os.makedirs(config, exist_ok=True)
        env["KICAD_CONFIG_HOME"] = config
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cli = self._kicad_cli_path()
        if cli:
            env["PATH"] = os.path.dirname(os.path.realpath(cli)) + os.pathsep + env.get("PATH", "")
        if widget_root:
            parts = [widget_root] + [d for d in (self._deps_dir, self._tools_dir) if d]
            env["PYTHONPATH"] = os.pathsep.join(parts)
        return env
