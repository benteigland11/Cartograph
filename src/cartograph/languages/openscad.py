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
# Helpers
# ---------------------------------------------------------------------------

_STL_EMPTY_BYTES = 84  # 80-byte header + 4-byte triangle count = minimum binary STL


def _split_params(params_str: str) -> list[str]:
    """Split a module parameter list by commas, respecting nested brackets.
    e.g. 'pos=[0,0,0], size=[10,10,10]' -> ['pos=[0,0,0]', 'size=[10,10,10]']"""
    params = []
    depth = 0
    current = []
    for ch in params_str:
        if ch in "([":
            depth += 1
            current.append(ch)
        elif ch in ")]":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            params.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        params.append("".join(current).strip())
    return [p for p in params if p]

def _stl_has_geometry(path: str) -> bool:
    """Return True if the STL file contains at least one triangle."""
    try:
        return os.path.getsize(path) > _STL_EMPTY_BYTES
    except OSError:
        return False


# Statements that are invalid at top level in src/ files.
# Everything here belongs inside a module — not at the file root.
_GEOMETRY_CALLS_RE = re.compile(
    r'^(?![ \t]*//)[ \t]*'
    r'(?:cube|sphere|cylinder|polyhedron|square|circle|polygon|text|'
    r'linear_extrude|rotate_extrude|import|surface|'
    r'union|difference|intersection|hull|minkowski|mirror|scale|rotate|translate|color|'
    r'render|projection|offset|'
    r'if|for|let)\s*[\(\;]',
    re.MULTILINE,
)

# Module parameter with no default: "ident" or "ident ," but NOT "ident = value"
_PARAM_NO_DEFAULT_RE = re.compile(
    r'(?<![=\w])(\b[a-zA-Z_]\w*)\s*(?=[,\)](?!\s*=))',
)

_ECHO_RE = re.compile(r'\becho\s*\(')
_RESOLUTION_RE = re.compile(r'(?:^|;)\s*\$f[nas]\s*=')
_INCLUDE_RE = re.compile(r'^\s*include\s*<', re.MULTILINE)


def _check_top_level_geometry(content: str, rel: str) -> list[str]:
    """Block geometry calls written outside any module in a src/ file."""
    blocks = []
    depth = 0  # brace depth — 0 means top level
    lines = content.splitlines()
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        depth_before = depth
        depth += stripped.count("{") - stripped.count("}")
        depth = max(depth, 0)
        if depth_before == 0 and _GEOMETRY_CALLS_RE.match(line):
            blocks.append(
                f"Top-level geometry in src/ at line {line_no}: {stripped!r} — "
                f"wrap all geometry in a module"
            )
    return blocks


def _strip_line_comments(content: str) -> str:
    """Remove // line comments from content, preserving line structure."""
    lines = []
    for line in content.splitlines():
        idx = line.find("//")
        lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(lines)


def _check_params_have_defaults(content: str, rel: str) -> list[str]:
    """Block public module parameters that have no default value.
    Private modules (name starting with _) are exempt — they are internal
    helpers always called with positional arguments."""
    blocks = []
    # Strip comments so parentheses in comments don't confuse the regex
    clean = _strip_line_comments(content)
    for m in re.finditer(r'\bmodule\s+(\w+)\s*\(([^)]*)\)', clean, re.DOTALL):
        module_name = m.group(1)
        if module_name.startswith("_"):
            continue  # private helper — defaults not required
        params_str = m.group(2).strip()
        line_no = content[: m.start()].count("\n") + 1
        if not params_str:
            continue
        for param in _split_params(params_str):
            if "=" not in param:
                blocks.append(
                    f"{rel}:{line_no}: parameter '{param}' in module '{module_name}' "
                    f"has no default — all parameters must have defaults"
                )
    return blocks


def _check_param_unit_comments(content: str, rel: str) -> list[str]:
    """Warn when module parameters lack inline unit comments (// mm, // degrees, etc.)."""
    warnings = []
    lines = content.splitlines()
    clean = _strip_line_comments(content)
    for m in re.finditer(r'\bmodule\s+(\w+)\s*\(([^)]*)\)', clean, re.DOTALL):
        module_name = m.group(1)
        if module_name.startswith("_"):
            continue  # private helper — unit comments not required
        params_str = m.group(2).strip()
        if not params_str:
            continue
        sig_start_line = content[: m.start(2)].count("\n")
        sig_end_line = content[: m.end(2)].count("\n")
        sig_lines = lines[sig_start_line: sig_end_line + 1]
        for param in _split_params(params_str):
            param_name = param.split("=")[0].strip()
            if not param_name:
                continue
            # Find the line in the signature that declares this parameter
            for i, sig_line in enumerate(sig_lines):
                if re.search(rf'\b{re.escape(param_name)}\s*[=,)]', sig_line):
                    if "//" not in sig_line:
                        line_no = sig_start_line + i + 1
                        warnings.append(
                            f"{rel}:{line_no}: parameter '{param_name}' in module '{module_name}' "
                            f"has no unit comment — add // mm, // degrees, etc."
                        )
                    break
    return warnings


def _parse_openscad_year(version_str: str) -> int | None:
    """Extract the release year from an openscad --version string.
    e.g. 'OpenSCAD version 2021.01.31' -> 2021. Returns None if unparseable."""
    m = re.search(r'\b(20\d{2})\b', version_str)
    return int(m.group(1)) if m else None


def _bosl2_installed() -> bool:
    """Check common OpenSCAD library paths for BOSL2."""
    import platform
    home = os.path.expanduser("~")
    candidates = []
    system = platform.system()
    if system == "Linux":
        candidates = [
            os.path.join(home, ".local", "share", "OpenSCAD", "libraries", "BOSL2"),
            "/usr/share/openscad/libraries/BOSL2",
        ]
    elif system == "Darwin":
        candidates = [
            os.path.join(home, "Documents", "OpenSCAD", "libraries", "BOSL2"),
            os.path.join(home, "Library", "Application Support", "OpenSCAD", "libraries", "BOSL2"),
        ]
    else:  # Windows
        candidates = [
            os.path.join(home, "Documents", "OpenSCAD", "libraries", "BOSL2"),
            os.path.join(os.environ.get("APPDATA", ""), "OpenSCAD", "libraries", "BOSL2"),
        ]
    return any(os.path.isdir(p) for p in candidates)


def _bosl2_detail() -> str:
    import platform
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Linux":
        path = os.path.join(home, ".local", "share", "OpenSCAD", "libraries", "BOSL2")
    elif system == "Darwin":
        path = os.path.join(home, "Documents", "OpenSCAD", "libraries", "BOSL2")
    else:
        path = os.path.join(home, "Documents", "OpenSCAD", "libraries", "BOSL2")
    if _bosl2_installed():
        return "found"
    return f"not found — clone github.com/revarbat/BOSL2 into {path}"


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
// Cartograph validates by rendering this file to a non-empty STL.
// Use assert() to enforce geometry contracts — a failing assert causes a
// non-zero exit and fails validation with a descriptive message.
use <../src/{module}.scad>

// Test: default parameters render without error
{module}();

// Test: custom dimensions
{module}(width = 40, height = 20, depth = 10);

// Test: minimum viable dimensions
{module}(width = 1, height = 1, depth = 1);

// Test: assert geometry contracts (OpenSCAD 2021+)
// Use assert() to validate parameter relationships and computed values.
// Example: assert that width must be positive
module test_contracts() {{
    w = 20;
    h = 10;
    assert(w > 0, "width must be positive");
    assert(h > 0, "height must be positive");
    assert(w >= h, "width should be >= height for this shape");
    {module}(width = w, height = h);
}}
test_contracts();
"""

_SCAD_EXAMPLE = """\
// Example usage of {name}
// Open in OpenSCAD and enable View > Customizer to adjust parameters interactively.
use <../src/{module}.scad>

/* [Parameters] */
// [TODO] Replace with your module's actual parameters and sensible ranges.
// Slider syntax: value; // [min:step:max]
// Dropdown syntax: "option"; // [option1, option2, option3]
width  = 20;  // [1:1:100]
height = 10;  // [1:1:100]
depth  = 5;   // [1:1:50]

/* [Hidden] */
$fn = 32;  // preview resolution — increase for final render

{module}(width = width, height = height, depth = depth);
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

    def check_available(self) -> tuple[bool, str]:
        """Require openscad binary AND version >= 2021 (needed for assert())."""
        if not shutil.which("openscad") and not shutil.which("openscad.cmd"):
            return False, "openscad not found - Install OpenSCAD 2021.01+ at openscad.org"
        ver = self.runtime_version() or ""
        year = _parse_openscad_year(ver)
        if year is not None and year < 2021:
            return False, f"OpenSCAD 2021.01+ required for assert() — found {ver.strip()}"
        return True, ""

    def check_optional(self) -> list[tuple[str, bool, str]]:
        """Surface BOSL2 availability as an informational doctor check."""
        return [("BOSL2", _bosl2_installed(), _bosl2_detail())]

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
            res = self._run(["openscad", "--version"], cwd=tempfile.gettempdir(), timeout=10)
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
        """Render each test_*.scad to a temp STL. Passes if exit 0 and mesh is non-empty."""
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
                elif not _stl_has_geometry(tmp.name):
                    errors.append(
                        f"{os.path.basename(test_file)}: rendered successfully but produced an empty mesh"
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
        """Render examples/example_usage.scad to a temp STL. Mesh must be non-empty."""
        ep = os.path.join(path, "examples", self.example_filename())
        if not os.path.exists(ep):
            return self._fail("examples/example_usage.scad not found")

        tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
        tmp.close()
        try:
            res = self._run(["openscad", "-o", tmp.name, ep], cwd=path, timeout=60)
            if res.returncode != 0:
                return self._fail((res.stderr or res.stdout or "").strip())
            if not _stl_has_geometry(tmp.name):
                return self._fail("example rendered successfully but produced an empty mesh")
            return self._ok()
        except FileNotFoundError:
            return self._fail("openscad not found — install OpenSCAD (openscad.org)")
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def scan_contamination(self, path: str, tech_stack: dict) -> dict:
        """
        OpenSCAD contamination checks:
          blocks : absolute paths, credentials, top-level geometry/control-flow in src/,
                   module parameters without defaults, include<> in src/, echo() in src/,
                   global resolution variables ($fn/$fa/$fs) in src/
          warnings: hardcoded URLs, unlisted external libraries, parameters without
                    unit comments
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
            [(f, True, False) for f in src_files]
            + [(f, False, False) for f in test_files]
            + [(f, False, True) for f in example_files]
        )

        for filepath, is_src, is_example in all_files:
            rel = os.path.relpath(filepath, path)
            try:
                content = open(filepath, encoding="utf-8", errors="replace").read()
            except Exception:
                continue

            if is_src:
                blocks.extend(_check_top_level_geometry(content, rel))
                blocks.extend(_check_params_have_defaults(content, rel))
                warnings.extend(_check_param_unit_comments(content, rel))
                # include <> executes the whole file on inclusion — use <> only
                for m in _INCLUDE_RE.finditer(content):
                    line_no = content[: m.start()].count("\n") + 1
                    blocks.append(
                        f"{rel}:{line_no}: use include<> in src/ — use use<> instead "
                        f"(include executes the full file on import)"
                    )
                # $fn/$fa/$fs override the consumer's resolution settings globally
                for line_no, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("//"):
                        continue
                    # Strip inline comment before pattern matching
                    code_part = line.split("//")[0]
                    if _RESOLUTION_RE.search(code_part):
                        blocks.append(
                            f"{rel}:{line_no}: global resolution variable ($fn/$fa/$fs) in src/ — "
                            f"expose as a module parameter instead"
                        )
                    if _ECHO_RE.search(code_part):
                        blocks.append(
                            f"{rel}:{line_no}: echo() in src/ — remove debug output before checkin"
                        )

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

            # Customizer annotations make modeling examples interactive in the OpenSCAD GUI
            if is_example and "/* [" not in content:
                warnings.append(
                    f"{rel}: no Customizer annotations found — add /* [Section] */ blocks "
                    f"with parameter ranges so users can tweak values in View > Customizer"
                )

        return {"blocks": blocks, "warnings": warnings}

    def cleanup(self, path: str) -> None:
        # OpenSCAD leaves no artifacts to clean up
        pass
