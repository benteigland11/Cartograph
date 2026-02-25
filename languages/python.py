"""Python language engine — uses pip + pytest + pytest-cov."""

import os
import sys

from .base import LanguageEngine

_COVERAGE_THRESHOLD = 80


class PythonEngine(LanguageEngine):
    name = "python"

    def install_deps(self, path: str, dependencies: list) -> None:
        all_deps = list(dependencies) + ["pytest", "pytest-cov"]
        print(f"   Installing {len(all_deps)} Python package(s)...")
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
