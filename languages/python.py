"""Python language engine — uses pip + pytest."""

import glob
import os
import sys

from .base import LanguageEngine


class PythonEngine(LanguageEngine):
    name = "python"

    def install_deps(self, path: str, dependencies: list) -> None:
        all_deps = list(dependencies) + ["pytest"]
        print(f"   Installing {len(all_deps)} Python package(s) (including pytest)...")
        for dep in all_deps:
            dep_name = dep if isinstance(dep, str) else dep.get("name", "")
            if dep_name:
                print(f"   - Installing {dep_name}...")
                self._run(
                    [sys.executable, "-m", "pip", "install", "-q", dep_name],
                    cwd=path,
                    timeout=60,
                )

    def run_tests(self, path: str) -> dict:
        test_files = glob.glob(os.path.join(path, "tests", "test_*.py"))
        if not test_files:
            return self._fail("No test_*.py files found in tests/")

        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        for test_file in test_files:
            rel = os.path.relpath(test_file, path)
            try:
                res = self._run(
                    [sys.executable, "-m", "pytest", rel],
                    cwd=path,
                    timeout=30,
                    env=env,
                )
            except Exception:
                # Fallback: run file directly
                res = self._run([sys.executable, rel], cwd=path, timeout=15, env=env)

            if res.returncode != 0:
                return self._fail(res.stderr or res.stdout)

        return self._ok()
