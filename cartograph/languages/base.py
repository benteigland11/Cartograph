"""
Base class for language engines.

Each engine handles:
  - validate_widget(path, dependencies): language-specific static checks
    before tests run. Returns {"passed": True} or {"passed": False, "error": str}.
  - install_deps(path, dependencies): install packages needed to run tests
  - run_tests(path): execute the test suite
  - find_test_files(path): return list of test files in tests/
  - example_filename(path): return expected example filename in examples/
  - run_example(path): execute the example and return pass/fail

Return shape for run_tests / validate_widget / run_example:
  {"passed": True}
  {"passed": False, "error": "<human-readable explanation>"}

To add a new language engine:
  1. Create languages/<lang>.py with a class that subclasses LanguageEngine.
     - Implement validate_widget(), install_deps(), run_tests()
     - Override find_test_files() and example_filename() if the defaults
       (test_*.py / example_usage.py) don't fit the language
     - Set supported = True (default is True on LanguageEngine; only set
       False if the engine exists but isn't ready yet — see TypeScriptEngine)
  2. Register in languages/registry.py:
     - Import the class and add it to _ENGINES under its canonical name
     - Add any short aliases to _ALIASES if needed
  3. Add a scaffold template in scaffolding/templates.py:
     - Write a function that creates src/, tests/, and examples/ stubs
     - Register it in the TEMPLATES dict at the bottom of that file
"""

import glob as _glob
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger("cartograph")

# Compiled once at module level — used by _dep_bare_name and _check_dep_pinning.
_DEP_SPLIT_RE = re.compile(r'[><=!~;\[]')
_PIN_RE = re.compile(r'[><=!~]|\d')


def _dep_bare_name(dep: str) -> str:
    """Return the bare package name from a dep string like 'fastapi>=0.128.0'."""
    return _DEP_SPLIT_RE.split(dep)[0].strip()


class LanguageEngine:
    name = "base"
    supported = True  # False on _UnsupportedEngine — checked before any validation runs

    def check_available(self) -> tuple[bool, str]:
        """Check that all system dependencies for this engine are installed.
        Returns (ok, message). Called before create/validate/checkin.
        """
        return True, ""

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

    def find_test_files(self, path: str) -> list[str]:
        """Return list of test files in tests/. Override per language."""
        return _glob.glob(os.path.join(path, "tests", "test_*.py"))

    def example_filename(self, path: str = "") -> str:
        """Return expected example filename in examples/. Override per language."""
        return "example_usage.py"

    def cleanup(self, path: str) -> None:
        """Remove any temp artifacts created during validation. Best-effort — never raises."""
        pass

    def run_example(self, path: str) -> dict:
        """Execute the example file. Called after install_deps."""
        ep = os.path.join(path, "examples", self.example_filename(path))
        res = subprocess.run(
            [sys.executable, ep],
            cwd=path, capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def required_files(self, path: str) -> list[tuple[str, str]]:
        """Return [(relative_path, error_hint)] for files that must exist before tests run."""
        return []

    def src_import_pattern(self) -> str | None:
        """Regex pattern used to verify an example imports from src/.
        Return None to skip the check for this language."""
        return None

    def watched_patterns(self, path: str) -> list[str]:
        """
        Glob patterns for files that feed the validation stamp fingerprint.
        A change to any matched file invalidates the stamp and forces re-validation.

        Override in subclasses to add language-specific manifest files
        (e.g. Cargo.toml for Rust, go.mod for Go, package.json for JS).
        """
        return [
            os.path.join(path, "src", "**", "*"),
            os.path.join(path, "tests", "**", "*"),
            os.path.join(path, "examples", "**", "*"),
            os.path.join(path, "widget.json"),
        ]

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
        Dependencies must be strings like 'fastapi>=0.128.0', not dicts.
        A valid dep string contains >=, ==, ~=, <=, !=, or a bare version number.
        """
        errors = []
        for dep in dependencies:
            if not isinstance(dep, str):
                name = dep.get("name", str(dep)) if isinstance(dep, dict) else str(dep)
                errors.append(
                    f"Dependency '{name}' must be a string like '{name}>=<version>', "
                    f"not a dict — use plain strings in tech_stack.dependencies"
                )
                continue
            if dep and not _PIN_RE.search(_DEP_SPLIT_RE.split(dep)[0]):
                bare = _dep_bare_name(dep)
                if bare == dep.strip():
                    errors.append(
                        f"Dependency '{dep}' has no version pin — "
                        f"use '{dep}>=<version>' for reproducibility"
                    )
        return errors
