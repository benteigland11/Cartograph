"""Nim language engine — uses nim + nimble test.

Source scanning is handled by scanners/nim_scanner.nim (native Nim) for
string/comment-aware detection. The Python side orchestrates validation
steps and parses the scanner's JSON output.
"""

import glob as _glob
import os
import re
import shutil
import tempfile

from .base import LanguageEngine, _dep_bare_name, log


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

        # 3. Native source scanner — runs nim_scanner.nim for string/comment-aware checks
        scanner = os.path.join(os.path.dirname(__file__), "scanners", "nim_scanner.nim")
        if src_files and os.path.exists(scanner):
            res = self._run(
                ["nim", "r", "--hints:off", "--warnings:off", scanner] + src_files,
                cwd=path, timeout=60,
            )
            findings = []
            if res.returncode == 0 and res.stdout.strip():
                import json
                try:
                    findings = json.loads(res.stdout.strip().splitlines()[-1])
                except (json.JSONDecodeError, IndexError):
                    pass

            # Group findings by kind for readable error messages
            _FINDING_MESSAGES = {
                "echo": "echo found in src/ - remove debug output before checkin:",
                "quit": "quit() found in src/ - widgets must not exit the process:",
                "ffi": "{.importc.} / {.compile.} found in src/ - C FFI makes widgets platform-dependent:",
                "global": "{.global.} found in src/ - widgets must not use global mutable state:",
                "main_module": "when isMainModule found in src/ - widgets are libraries, not executables:",
                "os_specific": "OS-specific when defined() found in src/ - widgets must validate on all platforms:",
                "risky_import": "Risky stdlib imports found in src/ - flagged for review:",
            }
            grouped: dict[str, list[str]] = {}
            for f in findings:
                kind = f.get("kind", "unknown")
                rel = os.path.relpath(f.get("file", ""), path)
                loc = f"  {rel}:{f.get('line', 0)}: {f.get('detail', '')}"
                grouped.setdefault(kind, []).append(loc)

            for kind, violations in grouped.items():
                header = _FINDING_MESSAGES.get(kind, f"{kind} found in src/:")
                errors.append(header + "\n" + "\n".join(violations))

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

            # Build a map of bare_name -> full dep string from widget.json
            wanted: dict[str, str] = {}
            for dep in dependencies:
                bare = _dep_bare_name(dep).lower()
                if bare and bare != "nim":
                    wanted[bare] = dep

            # Replace existing requires lines whose package is in wanted,
            # then append any that are missing entirely.
            declared: set[str] = set()
            lines = content.splitlines(keepends=True)
            new_lines = []
            for line in lines:
                m = re.match(r'(\s*requires\s+")([^"\s>=<!]+)([^"]*".*)', line)
                if m:
                    bare = m.group(2).lower()
                    declared.add(bare)
                    if bare in wanted:
                        new_lines.append(f'requires "{wanted[bare]}"\n')
                        log.debug("Updated requires for %s in %s", bare,
                                  os.path.basename(nimble_path))
                        continue
                new_lines.append(line)

            additions = [
                f'requires "{dep}"\n'
                for bare, dep in wanted.items()
                if bare not in declared
            ]
            new_lines.extend(additions)

            new_content = "".join(new_lines)
            if new_content != content:
                with open(nimble_path, "w") as f:
                    f.write(new_content)
                log.debug("Synced %d dep(s) to %s", len(additions),
                          os.path.basename(nimble_path))
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
