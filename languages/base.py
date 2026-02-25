"""
Base class for language engines.

Each language engine handles two responsibilities:
  - install_deps(path, dependencies): install packages needed to run tests
  - run_tests(path): execute the test suite and return a result dict

Return shape for run_tests:
  {"passed": True}
  {"passed": False, "error": "<output>"}
"""

import glob
import os
import subprocess
import sys


class LanguageEngine:
    name = "base"

    def install_deps(self, path: str, dependencies: list) -> None:
        """Install dependencies required to run tests. Best-effort — never raises."""
        pass

    def run_tests(self, path: str) -> dict:
        """
        Execute the test suite for a widget at `path`.
        Returns {"passed": True} or {"passed": False, "error": str}.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers

    def _run(self, cmd: list, cwd: str, timeout: int = 60, env: dict = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env or os.environ.copy(),
        )

    def _fail(self, output: str) -> dict:
        return {"passed": False, "error": str(output or "Unknown error")[:3000]}

    def _ok(self) -> dict:
        return {"passed": True}
