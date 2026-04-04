"""OpenSCAD language engine — parametric 3D modeling widgets."""

import glob as _glob
import logging
import os
import re
import shutil
import tempfile

from .base import LanguageEngine

log = logging.getLogger("cartograph")

# ---------------------------------------------------------------------------
# Scaffold templates
# ---------------------------------------------------------------------------

_SCAD_SRC = """\
// {name}
// Parametric module — all dimensions in millimeters.
//
// Parameters:
//   width  (mm) : overall width, default 20
//   height (mm) : overall height, default 10
//   depth  (mm) : overall depth, default 5

module {module}(
    width  = 20,   // mm — overall width
    height = 10,   // mm — overall height
    depth  = 5     // mm — overall depth
) {{
    // [TODO] Replace with your geometry
    cube([width, height, depth], center = true);
}}
"""

_SCAD_TEST = """\
// Tests for {module}
// Each render call must produce a non-empty mesh and exit with code 0.
use <../src/{module}.scad>

// Test: default parameters
{module}();

// Test: custom dimensions
{module}(width = 40, height = 20, depth = 10);

// Test: minimum viable dimensions
{module}(width = 1, height = 1, depth = 1);
"""

_SCAD_EXAMPLE = """\
// Example usage of {name}
use <../src/{module}.scad>

// Render with example parameters — edit to show a realistic use case
{module}(width = 30, height = 15, depth = 8);
"""


class OpenSCADEngine(LanguageEngine):
    name = "openscad"
    validation_version = 1
    file_ext = "scad"
    aliases = ["scad"]

    toolchain = {
        "openscad": "Install OpenSCAD 2021.01+ - openscad.org",
    }

    # No native scanner — contamination is simple enough for pure Python
    scanner_runner = None

    # OpenSCAD: no package manager. Dependencies declared in widget.json
    # are treated like heavy ML deps — must be pre-installed by the user.

    def scaffold(self, target_dir, module_name, display_name, **kwargs):
        with open(os.path.join(target_dir, "src", f"{module_name}.scad"), "w") as f:
            f.write(_SCAD_SRC.format(module=module_name, name=display_name))
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.scad"), "w") as f:
            f.write(_SCAD_TEST.format(module=module_name, name=display_name))
        with open(os.path.join(target_dir, "examples", "example_usage.scad"), "w") as f:
            f.write(_SCAD_EXAMPLE.format(module=module_name, name=display_name))

    def example_filename(self, path: str = "") -> str:
        return "example_usage.scad"

    def runtime_version(self) -> str | None:
        try:
            res = self._run(["openscad", "--version"], timeout=10)
            if res and res.returncode == 0:
                out = (res.stdout or res.stderr or "").strip()
                return out or None
        except FileNotFoundError:
            pass
        return None

    def install_deps(self, path: str, dependencies: list) -> None:
        """OpenSCAD has no package manager. Warn if deps declared."""
        if dependencies:
            log.warning(
                "OpenSCAD widget declares dependencies %s — these must be manually "
                "installed into your OpenSCAD library path (openscad.org/libraries). "
                "Cartograph cannot install them automatically.",
                dependencies,
            )

    def run_tests(self, path: str) -> dict:
        """Render each test_*.scad to a temp STL. Passes if all exit 0."""
        test_files = _glob.glob(os.path.join(path, "tests", "test_*.scad"))
        if not test_files:
            return self._fail("No test files found in tests/ — add at least one test_*.scad")

        errors = []
        for test_file in sorted(test_files):
            tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
            tmp.close()
            try:
                res = self._run(
                    ["openscad", "-o", tmp.name, test_file],
                    cwd=path,
                    timeout=60,
                )
                if res.returncode != 0:
                    errors.append(
                        f"{os.path.basename(test_file)}: {(res.stderr or res.stdout or '').strip()}"
                    )
            except FileNotFoundError:
                return self._fail("openscad not found — install OpenSCAD (openscad.org)")
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def run_example(self, path: str) -> dict:
        """Render examples/example_usage.scad to a temp STL."""
        ep = os.path.join(path, "examples", self.example_filename())
        if not os.path.exists(ep):
            return self._fail("examples/example_usage.scad not found")

        tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
        tmp.close()
        try:
            res = self._run(["openscad", "-o", tmp.name, ep], cwd=path, timeout=60)
            if res.returncode != 0:
                return self._fail((res.stderr or res.stdout or "").strip())
            return self._ok()
        except FileNotFoundError:
            return self._fail("openscad not found — install OpenSCAD (openscad.org)")
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def scan_contamination(self, path: str, tech_stack: dict) -> dict:
        """
        OpenSCAD contamination checks:
          blocks : absolute paths in include<>/use<>, credential-like strings
          warnings: hardcoded URLs, unlisted external libraries
        """
        blocks = []
        warnings = []

        _ABS_INCLUDE_RE = re.compile(
            r'(?:include|use)\s*<([^>]*)>',
        )
        _CREDENTIAL_RE = re.compile(
            r'(?:api_key|password|secret|token)\s*=\s*"[^"]{6,}"',
            re.IGNORECASE,
        )
        _URL_RE = re.compile(
            r'https?://(?!localhost|127\.0\.0\.1|example\.com|.*\.test/)[^\s"\'<>]+',
            re.IGNORECASE,
        )

        declared_deps = {d.split(">=")[0].split("==")[0].strip().lower()
                         for d in tech_stack.get("dependencies", [])}

        src_files = _glob.glob(os.path.join(path, "src", "*.scad"))
        test_files = _glob.glob(os.path.join(path, "tests", "*.scad"))
        example_files = _glob.glob(os.path.join(path, "examples", "*.scad"))

        all_files = (
            [(f, True) for f in src_files]
            + [(f, False) for f in test_files]
            + [(f, False) for f in example_files]
        )

        for filepath, is_src in all_files:
            rel = os.path.relpath(filepath, path)
            try:
                content = open(filepath, encoding="utf-8", errors="replace").read()
            except Exception:
                continue

            for m in _ABS_INCLUDE_RE.finditer(content):
                inc = m.group(1).strip()
                line_no = content[: m.start()].count("\n") + 1
                # Absolute Unix path or Windows drive letter
                if inc.startswith("/") or (len(inc) > 1 and inc[1] == ":"):
                    blocks.append(
                        f"Absolute path in include/use in {rel}:{line_no}: <{inc}>"
                    )
                # External library not declared in dependencies
                elif not inc.startswith(".") and not inc.startswith("../") and not inc.startswith("src/"):
                    lib_name = inc.split("/")[0].lower()
                    if lib_name not in declared_deps:
                        warnings.append(
                            f"Unlisted library in {rel}:{line_no}: <{inc}> — add to widget.json dependencies"
                        )

            for line_no, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                if _CREDENTIAL_RE.search(line):
                    blocks.append(f"Possible credential in {rel}:{line_no}: {stripped}")
                if is_src and _URL_RE.search(line):
                    warnings.append(f"Hardcoded URL in {rel}:{line_no}: {stripped}")

        return {"blocks": blocks, "warnings": warnings}

    def cleanup(self, path: str) -> None:
        # OpenSCAD leaves no artifacts to clean up
        pass
