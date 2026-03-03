"""Python language engine — uses pip + pytest + pytest-cov."""

import ast
import glob
import os
import sys

from .base import LanguageEngine, log

_COVERAGE_THRESHOLD = 80


class PythonEngine(LanguageEngine):
    name = "python"

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

    def install_deps(self, path: str, dependencies: list) -> None:
        all_deps = list(dependencies) + ["pytest", "pytest-cov"]
        log.debug("Installing %d Python package(s)...", len(all_deps))
        for dep in all_deps:
            dep_name = dep if isinstance(dep, str) else dep.get("name", "")
            if dep_name:
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
