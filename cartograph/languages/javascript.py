"""JavaScript / TypeScript language engine — uses npm + vitest.

React detection: if 'react' appears in tech_stack.dependencies, the engine
automatically enables the JSX transform (@vitejs/plugin-react) and jsdom
environment in vitest, and runs examples via react-dom/server + esbuild.
"""

import glob as _glob
import json
import os
import re
import shutil
import tempfile
import uuid

from .base import LanguageEngine, _dep_bare_name, log


_CONSOLE_LOG_RE = re.compile(r'console\s*\.\s*log\s*\(')

_REACT_DEV_DEPS = {
    "@vitejs/plugin-react": "^4.0.0",
    "@testing-library/react": "^14.0.0",
    "jsdom": "^24.0.0",
    "esbuild": "^0.20.0",
}

_VITEST_PLAIN = "export default { test: { include: ['tests/test_*.*'], globals: true } }\n"

_VITEST_REACT = """\
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    include: ['tests/test_*.*'],
    environment: 'jsdom',
    globals: true,
  }
})
"""


class JavaScriptEngine(LanguageEngine):
    name = "javascript"

    # ------------------------------------------------------------------ availability

    def check_available(self) -> tuple[bool, str]:
        missing = [tool for tool in ("node", "npx")
                   if not shutil.which(tool) and not shutil.which(tool + ".cmd")]
        if missing:
            return False, (
                f"JavaScript engine requires {' and '.join(missing)} — "
                f"run 'cartograph doctor' for setup instructions"
            )
        return True, ""

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _has_react(dependencies: list) -> bool:
        for dep in dependencies:
            if _dep_bare_name(dep).lower() == "react":
                return True
        return False

    def _read_deps(self, path: str) -> list:
        try:
            with open(os.path.join(path, "widget.json")) as f:
                return json.load(f).get("tech_stack", {}).get("dependencies", [])
        except Exception:
            return []

    # ------------------------------------------------------------------ validation

    def validate_widget(self, path: str, dependencies: list) -> dict:
        """Scan src/ for console.log() calls and unpinned dependencies."""
        errors = []

        # console.log check
        violations = []
        src_dir = os.path.join(path, "src")
        if os.path.isdir(src_dir):
            for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
                for fpath in _glob.glob(os.path.join(src_dir, "**", ext), recursive=True):
                    try:
                        with open(fpath) as f:
                            for line_no, line in enumerate(f, 1):
                                stripped = line.strip()
                                if stripped.startswith("//") or stripped.startswith("*"):
                                    continue
                                if _CONSOLE_LOG_RE.search(line):
                                    rel = os.path.relpath(fpath, path)
                                    violations.append(f"{rel}:{line_no}: {stripped}")
                    except Exception:
                        continue
        if violations:
            errors.append(
                "console.log() found in src/ — remove before checkin:\n" +
                "\n".join(violations)
            )

        errors.extend(self._check_dep_pinning(dependencies))

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    # ------------------------------------------------------------------ interface

    def src_import_pattern(self) -> str | None:
        return r"from\s+['\"]\.\.?/src/"

    def find_test_files(self, path: str) -> list[str]:
        files = []
        for ext in ("js", "jsx", "ts", "tsx"):
            files.extend(_glob.glob(os.path.join(path, "tests", "**", f"test_*.{ext}"), recursive=True))
        return files

    def example_filename(self, path: str = "") -> str:
        if path and self._has_react(self._read_deps(path)):
            return "example_usage.jsx"
        return "example_usage.js"

    def watched_patterns(self, path: str) -> list[str]:
        patterns = super().watched_patterns(path)
        patterns.append(os.path.join(path, "package.json"))
        return patterns

    # ------------------------------------------------------------------ install

    def install_deps(self, path: str, dependencies: list) -> None:
        has_react = self._has_react(dependencies)
        log.debug("Installing npm packages (react=%s)...", has_react)

        package_json_path = os.path.join(path, "package.json")

        if not os.path.exists(package_json_path):
            pkg = {
                "name": os.path.basename(path),
                "version": "1.0.0",
                "type": "module",
                "dependencies": {},
                "devDependencies": {"vitest": "^1.0.0"},
            }
            if has_react:
                pkg["devDependencies"].update(_REACT_DEV_DEPS)
            for dep in dependencies:
                bare = _dep_bare_name(dep)
                ver_part = dep[len(bare):].strip() or "*"
                if bare:
                    pkg["dependencies"][bare] = ver_part
            with open(package_json_path, "w") as f:
                json.dump(pkg, f, indent=2)
        else:
            with open(package_json_path) as f:
                pkg = json.load(f)
            dev = pkg.setdefault("devDependencies", {})
            changed = False
            if "vitest" not in dev and "vitest" not in pkg.get("dependencies", {}):
                dev["vitest"] = "^1.0.0"
                changed = True
            if has_react:
                for dep_name, dep_ver in _REACT_DEV_DEPS.items():
                    if dep_name not in dev and dep_name not in pkg.get("dependencies", {}):
                        dev[dep_name] = dep_ver
                        changed = True
            if changed:
                with open(package_json_path, "w") as f:
                    json.dump(pkg, f, indent=2)

        self._run(["npm", "install", "--silent"], cwd=path, timeout=120)

    # ------------------------------------------------------------------ tests

    def run_tests(self, path: str) -> dict:
        has_react = self._has_react(self._read_deps(path))
        config_path = os.path.join(path, f"vitest.config.{uuid.uuid4().hex}.js")
        try:
            with open(config_path, "w") as f:
                f.write(_VITEST_REACT if has_react else _VITEST_PLAIN)
            res = self._run(
                ["npx", "vitest", "run", "--config", os.path.basename(config_path)],
                cwd=path,
                timeout=60,
            )
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    # ------------------------------------------------------------------ example

    def run_example(self, path: str) -> dict:
        deps = self._read_deps(path)
        example_file = self.example_filename(path)
        example_path = os.path.join(path, "examples", example_file)

        if not self._has_react(deps):
            res = self._run(["node", example_path], cwd=path, timeout=30)
            if res.returncode != 0:
                return self._fail(res.stderr or res.stdout)
            return self._ok()

        # React JSX: bundle with esbuild (installed as devDep), run with node
        # .cjs forces CommonJS interpretation even when package.json has "type": "module"
        with tempfile.NamedTemporaryFile(suffix=".cjs", delete=False, dir=path) as f:
            bundle_path = f.name
        try:
            esbuild_name = "esbuild.cmd" if os.name == "nt" else "esbuild"
            esbuild = os.path.join(path, "node_modules", ".bin", esbuild_name)
            build = self._run(
                [esbuild, example_path,
                 "--bundle", "--platform=node", "--jsx=automatic",
                 f"--outfile={bundle_path}"],
                cwd=path, timeout=30,
            )
            if build.returncode != 0:
                return self._fail(f"esbuild failed:\n{build.stderr or build.stdout}")

            run = self._run(["node", bundle_path], cwd=path, timeout=30)
            if run.returncode != 0:
                return self._fail(run.stderr or run.stdout)
            return self._ok()
        finally:
            if os.path.exists(bundle_path):
                os.remove(bundle_path)

    # ------------------------------------------------------------------ cleanup

    def cleanup(self, path: str) -> None:
        import shutil
        nm = os.path.join(path, "node_modules")
        if os.path.exists(nm):
            shutil.rmtree(nm, ignore_errors=True)


class TypeScriptEngine(JavaScriptEngine):
    name = "typescript"

    def example_filename(self, path: str = "") -> str:
        if path and self._has_react(self._read_deps(path)):
            return "example_usage.tsx"
        return "example_usage.ts"

    def run_example(self, path: str) -> dict:
        deps = self._read_deps(path)
        example_file = self.example_filename(path)
        example_path = os.path.join(path, "examples", example_file)

        if not self._has_react(deps):
            res = self._run(["npx", "tsx", example_path], cwd=path, timeout=30)
            if res.returncode != 0:
                return self._fail(res.stderr or res.stdout)
            return self._ok()

        # React TSX: bundle with esbuild, run with node
        with tempfile.NamedTemporaryFile(suffix=".cjs", delete=False, dir=path) as f:
            bundle_path = f.name
        try:
            esbuild_name = "esbuild.cmd" if os.name == "nt" else "esbuild"
            esbuild = os.path.join(path, "node_modules", ".bin", esbuild_name)
            build = self._run(
                [esbuild, example_path,
                 "--bundle", "--platform=node", "--jsx=automatic",
                 f"--outfile={bundle_path}"],
                cwd=path, timeout=30,
            )
            if build.returncode != 0:
                return self._fail(f"esbuild failed:\n{build.stderr or build.stdout}")

            run = self._run(["node", bundle_path], cwd=path, timeout=30)
            if run.returncode != 0:
                return self._fail(run.stderr or run.stdout)
            return self._ok()
        finally:
            if os.path.exists(bundle_path):
                os.remove(bundle_path)
