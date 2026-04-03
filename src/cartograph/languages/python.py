"""Python language engine - uses pip + pytest + pytest-cov."""

import ast
import glob
import os
import re
import sys

from .base import LanguageEngine, _dep_bare_name, log

# Starter file contents for scaffold
_SRC_INIT = "# Package marker - add explicit exports here once the public API is stable.\n"

_SRC_TEMPLATE = '''\
def {module}(value):
    """{name}: process a value."""
    return value
'''

_TEST_TEMPLATE = '''\
def test_placeholder():
    # TODO: replace with real tests
    pass
'''

_EXAMPLE_TEMPLATE = '''\
"""
Example usage of {name}.

This file must run and exit cleanly with no user input, no network calls,
and no external services or API keys. Use fake/hardcoded data to demonstrate the API.
The widget's own declared dependencies are fine - the validator installs them first.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.{module} import {module}

# [TODO] Replace with a realistic call using fake data
result = {module}("hello")
print(f"Result: {{result}}")
'''

_COVERAGE_THRESHOLD = 80

# Large ML frameworks that cannot be installed in a temp venv during validation.
# These are hardware-dependent or extremely large — users must pre-install them.
# If a widget lists one of these as a dependency, validation will use the
# caller's existing environment install (if present) or fail with a clear message.
_HEAVY_ML_DEPS = {
    "torch", "torchvision", "torchaudio", "torch-nightly",
    "tensorflow", "tensorflow-gpu", "tensorflow-cpu", "tf-nightly",
    "keras",
    "jax", "jaxlib",
    "mxnet", "mxnet-cu102", "mxnet-cu110",
    "paddle", "paddlepaddle", "paddlepaddle-gpu",
    "flax", "optax",
}


class PythonEngine(LanguageEngine):
    name = "python"
    validation_version = 1

    def runtime_version(self) -> str | None:
        v = sys.version_info
        return f"python {v.major}.{v.minor}.{v.micro}"

    def check_available(self) -> tuple[bool, str]:
        import subprocess
        missing = []
        for tool in ("pytest", "coverage"):
            r = subprocess.run(
                [sys.executable, "-m", tool, "--version"],
                capture_output=True,
            )
            if r.returncode != 0:
                missing.append(tool)
        if missing:
            return False, (
                f"Python engine requires {' and '.join(missing)} — "
                f"run 'cartograph doctor' for setup instructions"
            )
        return True, ""

    def validate_widget(self, path: str, dependencies: list) -> dict:
        errors = []

        # 1. src/__init__.py must exist
        init = os.path.join(path, "src", "__init__.py")
        if not os.path.exists(init):
            errors.append("src/__init__.py is missing — add an empty one so the package is importable")

        # 2. No print() calls in src/ (AST-based: ignores docstrings and comments)
        src_files = glob.glob(os.path.join(path, "src", "**", "*.py"), recursive=True)
        for fpath in src_files:
            for lineno in self._find_print_calls(fpath):
                rel = os.path.relpath(fpath, path)
                errors.append(f"print() in {rel}:{lineno} — remove debug output from src/")

        # 3. Dependencies must have a version floor
        errors.extend(self._check_dep_pinning(dependencies))

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def _find_print_calls(self, fpath: str) -> list:
        """Return line numbers of print() calls in actual code, skipping docstrings."""
        try:
            with open(fpath) as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception:
            return []
        lines = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                lines.append(node.lineno)
        return lines

    _STDLIB = sys.stdlib_module_names
    _ENVVAR_RE = re.compile(r'os\.getenv\(|os\.environ')
    _SLEEP_MODULES = {"time", "asyncio"}
    _ABS_PATH_RE = re.compile(
        r'["\'](?:/home/|/Users/|/root/|[A-Za-z]:[/\\\\])[^"\']{3,}["\']'
    )
    _CREDENTIAL_RE = re.compile(
        r'(?:api_key|api_secret|secret_key|access_token|auth_token|password|passwd|credential)\s*=\s*["\'][^"\']{6,}["\']',
        re.IGNORECASE,
    )
    _URL_RE = re.compile(
        r'["\']https?://(?!(?:localhost|127\.0\.0\.1|(?:[\w-]+\.)*example\.com|[\w.-]+\.test(?:[/:"\'#?]|$)|schemas?\.))[^"\']{8,}["\']'
    )
    _IP_RE = re.compile(r'["\'](?:\d{1,3}\.){3}\d{1,3}(?::\d+)?["\']')

    def scan_contamination(self, path: str, widget: dict) -> dict:
        """Python contamination: AST-based checks for all contamination concerns."""
        blocks, warnings = [], []

        deps = widget.get("dependencies", [])
        dep_names = {_dep_bare_name(d).lower() for d in deps if isinstance(d, str)}
        own_modules = {"src"}
        src_dir = os.path.join(path, "src")
        if os.path.isdir(src_dir):
            for f in os.listdir(src_dir):
                if f.endswith(".py"):
                    own_modules.add(f[:-3])

        src_files = glob.glob(os.path.join(path, "src", "**", "*.py"), recursive=True)
        test_files = glob.glob(os.path.join(path, "tests", "**", "*.py"), recursive=True)

        for fpath in src_files + test_files:
            rel = os.path.relpath(fpath, path)
            is_src = fpath in src_files
            try:
                code = open(fpath).read()
            except Exception as e:
                blocks.append(f"Could not read source file {rel}: {e}")
                continue

            # Line-level checks (abs paths, credentials, URLs, IPs)
            for line_no, line in enumerate(code.splitlines(), 1):
                loc = f"{rel}:{line_no}"
                if is_src:
                    if self._ABS_PATH_RE.search(line):
                        blocks.append(f"Absolute path in {loc}: {line.strip()}")
                    if self._CREDENTIAL_RE.search(line):
                        blocks.append(f"Possible credential in {loc}: {line.strip()}")
                else:
                    if self._CREDENTIAL_RE.search(line):
                        warnings.append(f"Possible credential in test {loc} - verify it's fake: {line.strip()}")

            for m in self._URL_RE.finditer(code):
                line_no = code[:m.start()].count("\n") + 1
                warnings.append(f"Hardcoded URL in {rel}:{line_no}: {m.group()}")

            for m in self._IP_RE.finditer(code):
                line_no = code[:m.start()].count("\n") + 1
                if is_src:
                    blocks.append(f"Hardcoded IP in {rel}:{line_no}: {m.group()}")
                else:
                    warnings.append(f"Hardcoded IP in test {rel}:{line_no} - verify it's not project-specific: {m.group()}")

            # AST-based checks
            try:
                tree = ast.parse(code)
            except Exception:
                continue

            # Sleep/blocking calls (all files)
            # Collect bare names imported from sleep modules:
            # "from time import sleep" -> sleep_names = {"sleep"}
            # "from time import sleep as s" -> sleep_names = {"s"}
            sleep_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in self._SLEEP_MODULES:
                    for alias in node.names:
                        if alias.name == "sleep":
                            sleep_names.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                is_sleep = False
                # time.sleep() or asyncio.sleep()
                if (isinstance(func, ast.Attribute) and func.attr == "sleep"
                        and isinstance(func.value, ast.Name)
                        and func.value.id in self._SLEEP_MODULES):
                    is_sleep = True
                # from time import sleep; sleep()
                elif (isinstance(func, ast.Name) and func.id in sleep_names):
                    is_sleep = True

                if is_sleep:
                    if is_src:
                        blocks.append(
                            f"sleep() call in {rel}:{node.lineno} - widgets must not block the caller"
                        )
                    else:
                        # In tests/examples: warn if duration > 1 second
                        if (node.args and isinstance(node.args[0], ast.Constant)
                                and isinstance(node.args[0].value, (int, float))
                                and node.args[0].value > 1):
                            warnings.append(
                                f"sleep({node.args[0].value}) in {rel}:{node.lineno} - consider reducing sleep duration"
                            )

            # Remaining AST checks are src/ only
            if not is_src:
                continue

            # Unlisted imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0].lower()
                        if top and top not in self._STDLIB and top not in dep_names and top not in own_modules:
                            warnings.append(
                                f"Unlisted import '{top}' in {rel}:{node.lineno} - add to dependencies or remove"
                            )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0].lower()
                    if top and top not in self._STDLIB and top not in dep_names and top not in own_modules:
                        warnings.append(
                            f"Unlisted import '{top}' in {rel}:{node.lineno} - add to dependencies or remove"
                        )

            # Hardcoded values
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Assign):
                    warnings.extend(self._check_assign_targets(node.targets, node.value, node.lineno, rel))
                elif isinstance(node, ast.ClassDef):
                    for child in ast.iter_child_nodes(node):
                        if isinstance(child, ast.Assign):
                            warnings.extend(self._check_assign_targets(child.targets, child.value, child.lineno, rel))

            # os.environ/getenv
            for m in self._ENVVAR_RE.finditer(code):
                line_no = code[:m.start()].count("\n") + 1
                warnings.append(f"os.environ/getenv call in {rel}:{line_no} - verify it's not project-specific")

        return {"blocks": blocks, "warnings": warnings}

    def _check_assign_targets(self, targets, value, lineno, rel="") -> list[str]:
        """Check if an assignment's value is a hardcoded constant."""
        results = []
        names = []
        for t in targets:
            if isinstance(t, ast.Name):
                names.append(t.id)
        if not names:
            return results

        name = names[0]

        if isinstance(value, ast.Constant):
            val = value.value
            if isinstance(val, (int, float)):
                results.append(f"Hardcoded value in {rel}:{lineno}: {name} = {val} - consider making this a parameter")
            elif isinstance(val, str) and len(val) > 0:
                results.append(f"Hardcoded value in {rel}:{lineno}: {name} = \"{val[:60]}\" - consider making this a parameter")
        elif isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub):
            if isinstance(value.operand, ast.Constant):
                val = -value.operand.value
                if isinstance(val, (int, float)):
                    results.append(f"Hardcoded value in {rel}:{lineno}: {name} = {val} - consider making this a parameter")

        return results

    def scaffold(self, target_dir, module_name, display_name, **_):
        with open(os.path.join(target_dir, "src", "__init__.py"), "w") as f:
            f.write(_SRC_INIT)
        with open(os.path.join(target_dir, "src", f"{module_name}.py"), "w") as f:
            f.write(_SRC_TEMPLATE.format(module=module_name, name=display_name))
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
            f.write(_TEST_TEMPLATE)
        with open(os.path.join(target_dir, "examples", "example_usage.py"), "w") as f:
            f.write(_EXAMPLE_TEMPLATE.format(module=module_name, name=display_name))

    def src_import_pattern(self) -> str | None:
        return r'from src\.|import src\.'

    def _venv_python(self) -> str:
        """Return the venv python path if a venv was created, else sys.executable."""
        return getattr(self, "_venv_py", sys.executable)

    def install_deps(self, path: str, dependencies: list) -> None:
        import venv
        venv_dir = os.path.join(path, ".venv")
        log.debug("Creating isolated venv at %s", venv_dir)
        venv.create(venv_dir, with_pip=True, system_site_packages=True)

        # Locate the venv python
        if os.name == "nt":
            self._venv_py = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            self._venv_py = os.path.join(venv_dir, "bin", "python")

        all_deps = list(dependencies) + ["pytest", "pytest-cov"]
        log.debug("Installing %d Python package(s) into venv...", len(all_deps))
        py = self._venv_python()
        for dep in all_deps:
            dep_name = dep
            if not dep_name:
                continue
            # Normalise: strip version specifiers to get the base package name
            base_name = dep_name.split("[")[0].split("==")[0].split(">=")[0].split("<=")[0].split("!=")[0].strip().lower()
            if base_name in _HEAVY_ML_DEPS:
                # Check if it's already importable in the current environment
                import importlib.util
                import_name = base_name.replace("-", "_")
                if importlib.util.find_spec(import_name) is not None:
                    log.debug("Heavy ML dep '%s' found in environment - skipping install.", dep_name)
                else:
                    log.warning(
                        "Heavy ML dep '%s' is not installed and cannot be auto-installed by Cartograph. "
                        "Install it manually in your environment before running validation.",
                        dep_name,
                    )
                continue
            res = self._run(
                [py, "-m", "pip", "install", "-q", dep_name],
                cwd=path,
                timeout=60,
            )
            if res.returncode != 0:
                output = (res.stderr or res.stdout or "").strip()
                raise RuntimeError(
                    f"Failed to install Python dependency '{dep_name}'."
                    + (f"\n{output[:2000]}" if output else "")
                )

    def run_tests(self, path: str) -> dict:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        res = self._run(
            [
                self._venv_python(), "-m", "pytest", "tests/",
                "--cov=src",
                f"--cov-fail-under={_COVERAGE_THRESHOLD}",
                "--cov-report=term-missing",
                "--tb=short",
            ],
            cwd=path,
            timeout=60,
            env=env,
        )
        if res.returncode != 0:
            return self._fail(res.stdout + res.stderr)
        return self._ok()

    def run_example(self, path: str) -> dict:
        ep = os.path.join(path, "examples", self.example_filename(path))
        import subprocess
        res = subprocess.run(
            [self._venv_python(), ep],
            cwd=path, capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def cleanup(self, path: str) -> None:
        import shutil
        # Remove the isolated venv
        venv_dir = os.path.join(path, ".venv")
        if os.path.isdir(venv_dir):
            shutil.rmtree(venv_dir, ignore_errors=True)
        self._venv_py = None
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                if d in ("__pycache__", ".pytest_cache"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
