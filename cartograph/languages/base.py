"""
Base class for language engines.

Each engine handles:
  - validate_widget(path, dependencies): language-specific static checks
    before tests run. Returns {"passed": True} or {"passed": False, "error": str}.
  - install_deps(path, dependencies): install packages needed to run tests
  - run_tests(path): execute the test suite

Return shape for run_tests / validate_widget:
  {"passed": True}
  {"passed": False, "error": "<human-readable explanation>"}

To add a new language engine:
  1. Subclass LanguageEngine
  2. Implement validate_widget(), install_deps(), run_tests()
  3. Register in languages/registry.py
"""

import logging
import os
import re
import subprocess

log = logging.getLogger("cartograph")


class LanguageEngine:
    name = "base"

    def validate_widget(self, path: str, dependencies: list) -> dict:
        """
        Language-specific static checks on widget structure and source.
        Called before install_deps / run_tests.
        Override in subclasses to add language-specific rules.
        """
        return {"passed": True}

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

    def _run(self, cmd: list, cwd: str, timeout: int = 60,
             env: dict = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            env=env or os.environ.copy(),
        )

    def _fail(self, error: str) -> dict:
        return {"passed": False, "error": str(error or "Unknown error")[:3000]}

    def _ok(self) -> dict:
        return {"passed": True}

    # ------------------------------------------------------------------ shared checks

    @staticmethod
    def _check_dep_pinning(dependencies: list) -> list[str]:
        """
        Return a list of error messages for dependencies that have no version floor.
        A valid dep string contains >=, ==, ~=, <=, !=, or a bare version number.
        """
        _PIN_RE = re.compile(r'[><=!~]|\d')
        errors = []
        for dep in dependencies:
            name = dep if isinstance(dep, str) else dep.get("name", "")
            if name and not _PIN_RE.search(name.split("[")[0].split(";")[0]):
                # strip extras and markers before checking
                bare = re.split(r'[><=!~;\[]', name)[0].strip()
                if bare == name.strip():
                    errors.append(
                        f"Dependency '{name}' has no version pin — "
                        f"use '{name}>=<version>' for reproducibility"
                    )
        return errors
