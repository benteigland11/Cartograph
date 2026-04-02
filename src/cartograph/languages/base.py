"""
Base class for language engines.

To add a new language engine (simple case - no custom validation logic):

  1. Create languages/<lang>.py:

     class LuaEngine(LanguageEngine):
         name = "lua"
         file_ext = "lua"
         toolchain = {"lua": "Install Lua - lua.org",
                      "luarocks": "Install LuaRocks - luarocks.org"}
         test_command = ["lua", "tests/run_tests.lua"]
         example_command = ["lua"]
         dep_install_command = ["luarocks", "install"]
         scanner_runner = ["lua"]
         import_pattern = r'require.*src%.'

  2. Create a native scanner at languages/scanners/lua_scanner.lua
     that outputs a JSON array of {kind, file, line, detail} objects.
     Define scanner_messages on the class to map kind -> human-readable header.

  3. Add a scaffold() method on the engine class to write starter files
     for src/, tests/, and examples/. This keeps everything about the
     language in one place.

  That's it. The engine is auto-discovered - no registry edits needed.
  Doctor picks it up automatically via check_available().

  For custom behavior (compile checks, React detection, etc.), override
  any method. See nim.py and javascript.py for examples.

Return shape for run_tests / validate_widget / run_example:
  {"passed": True}
  {"passed": False, "error": "<human-readable explanation>"}
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


def _dep_bare_name(dep) -> str:
    """Return the bare package name from a dep string like 'fastapi>=0.128.0' or a dict."""
    if isinstance(dep, dict):
        return dep.get("name", "")
    return _DEP_SPLIT_RE.split(dep)[0].strip()


class LanguageEngine:
    name = "base"
    supported = True       # set False to hide a WIP engine from users
    aliases: list = []     # short names, e.g. ["js"] for javascript

    # -- Declarative attributes (set these instead of overriding methods) ------
    # If set, the base class provides default implementations for
    # check_available, validate_widget, install_deps, run_tests, run_example,
    # find_test_files, and example_filename automatically.

    file_ext: str = ""               # e.g. "lua", "nim", "js" - the source file extension
    toolchain: dict = {}             # {"binary": "install hint"} - checked by check_available()
    test_command: list = []          # e.g. ["lua", "tests/run_tests.lua"] - run from widget root
    example_command: list = []       # e.g. ["lua"] - example file path is appended
    dep_install_command: list = []   # e.g. ["luarocks", "install"] - dep name is appended
    scanner_runner: list = []        # e.g. ["lua"] - runs scanners/<name>_scanner.<ext>
    scanner_messages: dict = {}      # {finding_kind: "human-readable header"} - errors (block checkin)
    scanner_warning_messages: dict = {}  # {finding_kind: "human-readable header"} - warnings (don't block)
    import_pattern: str = ""         # regex for "does example import from src?"
    manifest_patterns: list = []     # e.g. ["*.rockspec"] - added to watched_patterns

    # -- Methods (override for custom behavior) --------------------------------

    def check_available(self) -> tuple[bool, str]:
        """Check that all system dependencies for this engine are installed."""
        if not self.toolchain:
            return True, ""
        import shutil
        missing = [
            name for name in self.toolchain
            if not shutil.which(name) and not shutil.which(name + ".cmd")
        ]
        if missing:
            hints = [self.toolchain[m] for m in missing]
            return False, (
                f"{self.name.capitalize()} engine requires {' and '.join(missing)} - "
                + "; ".join(hints)
            )
        return True, ""

    def validate_widget(self, path: str, dependencies: list) -> dict:
        """Source scanning + dep pinning check. Override to add custom steps."""
        errors = []
        warnings = []

        # Run native scanner if configured
        if self.file_ext and self.scanner_runner:
            src_dir = os.path.join(path, "src")
            src_files = _glob.glob(
                os.path.join(src_dir, "**", f"*.{self.file_ext}"), recursive=True
            )
            scanner = os.path.join(
                os.path.dirname(__file__), "scanners",
                f"{self.name}_scanner.{self.file_ext}"
            )
            scan_errors, scan_warnings, _ = self._run_native_scanner(
                scanner_path=scanner,
                runner=self.scanner_runner,
                src_files=src_files,
                cwd=path,
                finding_messages=self.scanner_messages,
            )
            errors.extend(scan_errors)
            warnings.extend(scan_warnings)

        errors.extend(self._check_dep_pinning(dependencies))

        if errors:
            result = self._fail("\n".join(errors))
        else:
            result = self._ok()
        if warnings:
            result["warnings"] = warnings
        return result

    def scan_contamination(self, path: str, widget: dict) -> dict:
        """Scan for contamination. Override to implement language-specific checks.

        Each language engine must implement detection for the following using
        native tooling (AST, native scanners) that understands the language's
        strings, comments, and code constructs.

        Required checks (blocks - hard failures, no override):
          1. Absolute paths    - /home/, /Users/, /root/, C:\\ in string literals
          2. Credentials       - api_key/secret/token/password assignments in src/
                                 (in tests/, emit as warning instead)
          3. Hardcoded URLs    - http(s):// URLs (except localhost, example.com)
          4. Hardcoded IPs     - IP addresses in string literals
          5. Sleep/blocking    - sleep calls in src/ (widgets must not block the caller)
                                 (in tests/examples, warn if duration > 1 second)

        Required checks (warnings - overridable with --override-warnings):
          6. Hardcoded values  - numeric and string constant assignments
          7. Env var access    - language-specific env var APIs
          8. Unlisted imports  - imports not in widget.json dependencies or stdlib

        Both src/ and tests/ files must be scanned. Credentials in tests/ are
        warnings (verify they're fake), not blocks.

        Returns {"blocks": [...], "warnings": [...]}.
        See python.py, javascript.py, nim.py for reference implementations.

        The base class provides a regex fallback that covers checks 1-4.
        Check 5 (sleep/blocking) REQUIRES language-native tooling - sleep calls
        cannot be reliably detected with regex because language-specific call
        syntax must be understood (e.g. time.sleep vs a variable named sleep_timer).
        Each engine must implement sleep detection natively.
        Override with native tooling for accurate detection.
        """
        blocks, warnings = [], []
        src_files, test_files = self._collect_source_files(path)

        abs_path_re = re.compile(r'["\'](?:/home/|/Users/|/root/|[A-Za-z]:[/\\\\])[^"\']{3,}["\']')
        credential_re = re.compile(
            r'(?:api_key|api_secret|secret_key|access_token|auth_token|password|passwd|credential)\s*=\s*["\'][^"\']{6,}["\']',
            re.IGNORECASE,
        )
        url_re = re.compile(
            r'["\']https?://(?!(?:localhost|127\.0\.0\.1|(?:[\w-]+\.)*example\.com|schemas?\.))[^"\']{8,}["\']'
        )
        ip_re = re.compile(r'["\'](?:\d{1,3}\.){3}\d{1,3}(?::\d+)?["\']')
        number_re = re.compile(r'^\s*\w+\s*=\s*-?\d+\.?\d*(?:e[+-]?\d+)?\s*$', re.IGNORECASE)

        for fpath in src_files + test_files:
            rel = os.path.relpath(fpath, path)
            is_src = fpath in src_files
            try:
                code = open(fpath).read()
            except Exception:
                continue

            for line_no, line in enumerate(code.splitlines(), 1):
                loc = f"{rel}:{line_no}"
                if is_src:
                    if abs_path_re.search(line):
                        blocks.append(f"Absolute path in {loc}: {line.strip()}")
                    if credential_re.search(line):
                        blocks.append(f"Possible credential in {loc}: {line.strip()}")
                    if url_re.search(line):
                        blocks.append(f"Hardcoded URL in {loc}: {line.strip()}")
                    if ip_re.search(line):
                        blocks.append(f"Hardcoded IP in {loc}: {line.strip()}")
                    if number_re.match(line):
                        warnings.append(f"Hardcoded value in {loc}: {line.strip()} - consider making this a parameter")
                else:
                    if credential_re.search(line):
                        warnings.append(f"Possible credential in test {loc} - verify it's fake: {line.strip()}")

        return {"blocks": blocks, "warnings": warnings}

    def _collect_source_files(self, path: str) -> tuple[list[str], list[str]]:
        """Return (src_files, test_files) for this language. Override for multi-ext languages."""
        ext = self.file_ext or "*"
        src_files = _glob.glob(os.path.join(path, "src", "**", f"*.{ext}"), recursive=True)
        test_files = _glob.glob(os.path.join(path, "tests", "**", f"*.{ext}"), recursive=True)
        return src_files, test_files

    def install_deps(self, path: str, dependencies: list) -> None:
        """Install dependencies required to run tests. Best-effort."""
        if not self.dep_install_command or not dependencies:
            return
        for dep in dependencies:
            bare = _dep_bare_name(dep)
            if not bare:
                continue
            log.debug("Installing %s package: %s", self.name, bare)
            self._run(self.dep_install_command + [bare], cwd=path, timeout=120)

    def run_tests(self, path: str) -> dict:
        """Execute the test suite. Override for custom test runners."""
        if not self.test_command:
            raise NotImplementedError(
                f"{self.name} engine must set test_command or override run_tests()"
            )
        res = self._run(self.test_command, cwd=path, timeout=120)
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def find_test_files(self, path: str) -> list[str]:
        """Return list of test files in tests/."""
        ext = self.file_ext or "py"
        return _glob.glob(os.path.join(path, "tests", f"test_*.{ext}"))

    def example_filename(self, path: str = "") -> str:
        """Return expected example filename in examples/."""
        ext = self.file_ext or "py"
        return f"example_usage.{ext}"

    def cleanup(self, path: str) -> None:
        """Remove any temp artifacts created during validation. Best-effort."""
        pass

    def run_example(self, path: str) -> dict:
        """Execute the example file. Called after install_deps."""
        ep = os.path.join(path, "examples", self.example_filename(path))
        if self.example_command:
            res = self._run(self.example_command + [ep], cwd=path, timeout=60)
        else:
            res = subprocess.run(
                [sys.executable, ep],
                cwd=path, capture_output=True, text=True, timeout=60,
            )
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def scaffold(self, target_dir: str, module_name: str, display_name: str, **kwargs) -> None:
        """Write starter src/, tests/, and examples/ files for a new widget.
        Override this to co-locate the scaffold template with the engine.
        Return None if this engine has no scaffold (falls back to templates.py).
        """
        return None

    def required_files(self, path: str) -> list[tuple[str, str]]:
        """Return [(relative_path, error_hint)] for files that must exist before tests run."""
        return []

    def src_import_pattern(self) -> str | None:
        """Regex pattern used to verify an example imports from src/."""
        return self.import_pattern or None

    def watched_patterns(self, path: str) -> list[str]:
        """Glob patterns for files that feed the validation stamp fingerprint."""
        patterns = [
            os.path.join(path, "src", "**", "*"),
            os.path.join(path, "tests", "**", "*"),
            os.path.join(path, "examples", "**", "*"),
            os.path.join(path, "widget.json"),
        ]
        for pat in self.manifest_patterns:
            patterns.extend(_glob.glob(os.path.join(path, pat)))
        return patterns

    # ------------------------------------------------------------------ helpers

    def _run_native_scanner(self, scanner_path: str, runner: list,
                            src_files: list, cwd: str,
                            finding_messages: dict = None,
                            warning_messages: dict = None) -> tuple[list[str], list[str], list[str]]:
        """
        Run a native language scanner and return (errors, warnings, blocks).

        scanner_path: absolute path to the scanner source file
        runner: command prefix to execute it, e.g. ["node"] or ["nim", "r", "--hints:off"]
        src_files: list of source files to scan
        finding_messages: dict mapping finding kind -> human-readable header (errors)
        warning_messages: dict mapping finding kind -> human-readable header (warnings)

        The scanner must output a JSON array of objects with keys:
          kind, file, line, detail, [severity]
        Severity values: "error" (default), "warning", "block".
        """
        if not src_files or not os.path.exists(scanner_path):
            return [], [], []

        res = self._run(
            runner + [scanner_path] + src_files,
            cwd=cwd, timeout=60,
        )

        findings = []
        if res.returncode == 0 and res.stdout.strip():
            import json
            try:
                # Scanner may emit other output before the JSON line
                findings = json.loads(res.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                pass

        if not findings:
            return [], [], []

        finding_messages = finding_messages or {}
        warning_messages = warning_messages or self.scanner_warning_messages or {}
        warning_kinds = set(warning_messages.keys())

        error_grouped: dict[str, list[str]] = {}
        warn_grouped: dict[str, list[str]] = {}
        block_grouped: dict[str, list[str]] = {}
        for f in findings:
            kind = f.get("kind", "unknown")
            severity = f.get("severity", "error")
            rel = os.path.relpath(f.get("file", ""), cwd)
            loc = f"  {rel}:{f.get('line', 0)}: {f.get('detail', '')}"
            if severity == "block":
                block_grouped.setdefault(kind, []).append(loc)
            elif severity == "warning" or kind in warning_kinds:
                warn_grouped.setdefault(kind, []).append(loc)
            else:
                error_grouped.setdefault(kind, []).append(loc)

        all_messages = {**finding_messages, **warning_messages}

        errors = []
        for kind, violations in error_grouped.items():
            header = all_messages.get(kind, f"{kind} found in src/:")
            errors.append(header + "\n" + "\n".join(violations))

        warnings = []
        for kind, violations in warn_grouped.items():
            header = all_messages.get(kind, f"{kind} found in src/:")
            warnings.append(header + "\n" + "\n".join(violations))

        blocks = []
        for kind, violations in block_grouped.items():
            header = all_messages.get(kind, f"{kind} found in src/:")
            blocks.append(header + "\n" + "\n".join(violations))

        return errors, warnings, blocks

    def _run(self, cmd: list, cwd: str, timeout: int = 60,
             env: dict = None) -> subprocess.CompletedProcess:
        # On Windows, shell scripts like npm/npx need shell=True or the .cmd extension.
        # Using shell=True is simpler and handles both cases.
        use_shell = os.name == "nt"
        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            env=env or os.environ.copy(),
            shell=use_shell,
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
