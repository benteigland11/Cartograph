"""Nim language engine — uses nim + nimble test."""

import glob as _glob
import os
import re
import shutil
import tempfile

from .base import LanguageEngine, _dep_bare_name, log

# Anchored to start of statement — avoids matching echo inside string literals
_ECHO_RE = re.compile(r'^\s*echo\b')
# Matches quit() and system.quit() — widgets must not terminate the process
_QUIT_RE = re.compile(r'^\s*(?:system\.)?quit\s*[\(\s]')
# C FFI pragmas — make widgets platform-dependent and unvalidatable everywhere
_IMPORTC_RE = re.compile(r'\{\.importc')
_COMPILE_RE = re.compile(r'\{\.compile')
# Global mutable state pragma
_GLOBAL_RE = re.compile(r'\{\.global\.\}')
# isMainModule guard — signals executable intent, not library code
_MAIN_MODULE_RE = re.compile(r'\bwhen\s+isMainModule\b')
# OS-targeting when defined() — blocks generalised validation
_OS_WHEN_RE = re.compile(
    r'\bwhen\s+defined\s*\(\s*'
    r'(windows|linux|macosx|osx|posix|unix|freebsd|netbsd|openbsd|haiku|android|ios)',
    re.IGNORECASE,
)


class NimEngine(LanguageEngine):
    name = "nim"

    def check_available(self) -> tuple[bool, str]:
        missing = [t for t in ("nim", "nimble") if not shutil.which(t)]
        if missing:
            return False, (
                f"Nim engine requires {' and '.join(missing)} — "
                f"run 'cartograph doctor' for setup instructions"
            )
        return True, ""

    def validate_widget(self, path: str, dependencies: list) -> dict:
        errors = []

        # 1. src/ must contain at least one .nim file
        src_dir = os.path.join(path, "src")
        src_files = _glob.glob(os.path.join(src_dir, "**", "*.nim"), recursive=True)
        if not src_files:
            errors.append("src/ contains no .nim files — add at least one source file")

        # 2. Semantic check — nim check catches type errors, undefined symbols, bad syntax.
        # Runs before install_deps, so "cannot find module" errors for external packages
        # are filtered out — those will surface as compile errors in nimble test instead.
        for fpath in src_files:
            rel = os.path.relpath(fpath, path)
            try:
                res = self._run(
                    ["nim", "check", "--hints:off", "--warnings:off",
                     f"--path:{src_dir}", fpath],
                    cwd=path, timeout=60,
                )
                if res.returncode != 0:
                    output = (res.stderr or res.stdout).strip()
                    lines = output.splitlines()
                    # If any line is a missing-import error (external dep not yet installed),
                    # all subsequent errors are cascades — skip this file entirely.
                    missing_import = any(
                        "cannot find module" in l.lower() or "cannot open file" in l.lower()
                        for l in lines
                    )
                    if missing_import:
                        continue
                    real_errors = [l for l in lines if l.strip()]
                    if real_errors:
                        errors.append(f"nim check failed on {rel}:\n" + "\n".join(real_errors))
            except FileNotFoundError:
                pass  # check_available() will have already flagged this

        # 3. Static source scan — skip comment lines
        echo_violations = []
        quit_violations = []
        ffi_violations = []
        global_violations = []
        main_module_violations = []
        os_when_violations = []
        for fpath in src_files:
            try:
                with open(fpath) as f:
                    for line_no, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            continue
                        rel = os.path.relpath(fpath, path)
                        loc = f"  {rel}:{line_no}: {stripped}"
                        if _ECHO_RE.match(line):
                            echo_violations.append(loc)
                        if _QUIT_RE.match(line):
                            quit_violations.append(loc)
                        if _IMPORTC_RE.search(line) or _COMPILE_RE.search(line):
                            ffi_violations.append(loc)
                        if _GLOBAL_RE.search(line):
                            global_violations.append(loc)
                        if _MAIN_MODULE_RE.search(line):
                            main_module_violations.append(loc)
                        if _OS_WHEN_RE.search(line):
                            os_when_violations.append(loc)
            except Exception:
                continue

        if echo_violations:
            errors.append("echo found in src/ — remove debug output before checkin:\n" + "\n".join(echo_violations))
        if quit_violations:
            errors.append("quit() found in src/ — widgets must not exit the process:\n" + "\n".join(quit_violations))
        if ffi_violations:
            errors.append(
                "{.importc.} / {.compile.} found in src/ — C FFI makes widgets platform-dependent "
                "and unvalidatable. Wrap C dependencies in a separate project:\n" + "\n".join(ffi_violations)
            )
        if global_violations:
            errors.append("{.global.} found in src/ — widgets must not use global mutable state:\n" + "\n".join(global_violations))
        if main_module_violations:
            errors.append(
                "when isMainModule found in src/ — widgets are libraries, not executables. "
                "Move this logic to examples/:\n" + "\n".join(main_module_violations)
            )
        if os_when_violations:
            errors.append(
                "OS-specific 'when defined(...)' found in src/ — widgets must validate on all platforms:\n" +
                "\n".join(os_when_violations)
            )

        # 4. Dependencies must have a version floor
        errors.extend(self._check_dep_pinning(dependencies))

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def required_files(self, path: str) -> list[tuple[str, str]]:
        if _glob.glob(os.path.join(path, "*.nimble")):
            return []
        # Return a sentinel path that won't exist — triggers the check failure
        return [("<widget>.nimble", "A .nimble file is required at the widget root — run 'cartograph create' to scaffold it")]

    def src_import_pattern(self) -> str | None:
        # Examples run with --path:src, so bare `import module_name` resolves to src/
        return r'^import\s+\w+'

    def install_deps(self, path: str, dependencies: list) -> None:
        if not dependencies:
            self._nimble_dir = None
            return

        # Isolated install — each validation gets its own NIMBLE_DIR so packages
        # from one widget never bleed into another's compilation environment.
        tmpdir = tempfile.mkdtemp(prefix="cartograph_nim_")
        self._nimble_dir = tmpdir
        env = {**os.environ, "NIMBLE_DIR": tmpdir}
        log.debug("Nim isolated env: NIMBLE_DIR=%s", tmpdir)

        for dep in dependencies:
            bare = _dep_bare_name(dep)
            if not bare:
                continue
            log.debug("Installing Nim package: %s", bare)
            self._run(["nimble", "install", "-y", bare], cwd=path, timeout=120, env=env)

        self._sync_nimble_requires(path, dependencies)

    def _sync_nimble_requires(self, path: str, dependencies: list) -> None:
        """Keep .nimble requires in sync with widget.json dependencies."""
        matches = _glob.glob(os.path.join(path, "*.nimble"))
        if not matches:
            return
        nimble_path = matches[0]
        if not os.path.exists(nimble_path):
            return
        try:
            with open(nimble_path) as f:
                content = f.read()

            # Collect bare names already declared in requires lines
            declared = set(re.findall(r'requires\s+"([^"\s>=<!]+)', content))

            additions = []
            for dep in dependencies:
                bare = _dep_bare_name(dep).lower()
                if bare and bare != "nim" and bare not in declared:
                    # Use the full dep string as the requires value
                    additions.append(f'requires "{dep}"\n')

            if additions:
                with open(nimble_path, "a") as f:
                    f.writelines(additions)
                log.debug("Synced %d dep(s) to %s", len(additions), os.path.basename(nimble_path))
        except Exception as e:
            log.debug("Could not sync .nimble requires: %s", e)

    def run_tests(self, path: str) -> dict:
        env = self._nimble_env()
        try:
            res = self._run(["nimble", "test", "-y"], cwd=path, timeout=120, env=env)
        except FileNotFoundError:
            return self._fail("Nim not found — install Nim toolchain.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def find_test_files(self, path: str) -> list[str]:
        return _glob.glob(os.path.join(path, "tests", "test_*.nim"))

    def example_filename(self, path: str = "") -> str:
        return "example_usage.nim"

    def run_example(self, path: str) -> dict:
        ep = os.path.join(path, "examples", self.example_filename())
        src_path = os.path.join(path, "src")
        env = self._nimble_env()
        cmd = ["nim", "r", f"--path:{src_path}"]
        # `nim r` doesn't resolve NIMBLE_DIR on its own — add installed package
        # dirs as explicit --path flags so external deps compile correctly.
        nimble_dir = getattr(self, "_nimble_dir", None)
        if nimble_dir:
            pkgs2 = os.path.join(nimble_dir, "pkgs2")
            if os.path.isdir(pkgs2):
                for pkg in os.listdir(pkgs2):
                    pkg_path = os.path.join(pkgs2, pkg)
                    if os.path.isdir(pkg_path):
                        cmd.append(f"--path:{pkg_path}")
        cmd.append(ep)
        try:
            res = self._run(cmd, cwd=path, timeout=60, env=env)
        except FileNotFoundError:
            return self._fail("Nim not found — install Nim toolchain.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def cleanup(self, path: str) -> None:
        self._cleanup_nimble_dir()

    def _nimble_env(self) -> dict:
        """Return env dict with NIMBLE_DIR set if an isolated dir was created."""
        nimble_dir = getattr(self, "_nimble_dir", None)
        if nimble_dir:
            return {**os.environ, "NIMBLE_DIR": nimble_dir}
        return os.environ.copy()

    def _cleanup_nimble_dir(self) -> None:
        nimble_dir = getattr(self, "_nimble_dir", None)
        if nimble_dir and os.path.exists(nimble_dir):
            shutil.rmtree(nimble_dir, ignore_errors=True)
            log.debug("Removed isolated Nim env: %s", nimble_dir)
        self._nimble_dir = None

    def watched_patterns(self, path: str) -> list[str]:
        patterns = super().watched_patterns(path)
        patterns.extend(_glob.glob(os.path.join(path, "*.nimble")))
        return patterns
