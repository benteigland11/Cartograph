"""Python language engine - uses pip + pytest + pytest-cov."""

import ast
import glob
import os
import sys

from .base import LanguageEngine, log

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

    def install_deps(self, path: str, dependencies: list) -> None:
        all_deps = list(dependencies) + ["pytest", "pytest-cov"]
        log.debug("Installing %d Python package(s)...", len(all_deps))
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
                    log.debug("Heavy ML dep '%s' found in environment — skipping install.", dep_name)
                else:
                    log.warning(
                        "Heavy ML dep '%s' is not installed and cannot be auto-installed by Cartograph. "
                        "Install it manually in your environment before running validation.",
                        dep_name,
                    )
                continue
            self._run(
                [sys.executable, "-m", "pip", "install", "-q", dep_name],
                cwd=path,
                timeout=60,
            )

    def run_tests(self, path: str) -> dict:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        res = self._run(
            [
                sys.executable, "-m", "pytest", "tests/",
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

    def cleanup(self, path: str) -> None:
        import shutil
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                if d in ("__pycache__", ".pytest_cache"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
