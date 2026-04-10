"""JavaScript / TypeScript language engine - uses npm + vitest.

React detection: if 'react' appears in tech_stack.dependencies, the engine
automatically enables the JSX transform (@vitejs/plugin-react) and jsdom
environment in vitest, and runs examples via react-dom/server + esbuild.

Source scanning is handled by scanners/js_scanner.js (native JS) for
string/comment/template-literal-aware detection.
"""

import glob as _glob
import json
import os
import shutil
import tempfile
import uuid

from .base import LanguageEngine, _dep_bare_name, log

# -- Scaffold templates --------------------------------------------------------

# Plain JS (backend, data, infra, universal, etc.)
_JS_PLAIN_SRC = '''\
/**
 * {name}
 */
export function {module}(value) {{
  return value
}}
'''

_JS_PLAIN_TEST = '''\
import {{ {module} }} from '../src/{module}.js'

test('placeholder', () => {{
  // TODO: replace with real tests
  expect({module}('hello')).toBe('hello')
}})
'''

_JS_PLAIN_EXAMPLE = '''\
/**
 * Example usage of {name}.
 *
 * This file must run and exit cleanly with no user input, no network calls,
 * and no external services or API keys. Use fake/hardcoded data to demonstrate the API.
 * The widget's own declared dependencies are fine - the validator installs them first.
 */
import {{ {module} }} from '../src/{module}.js'

// [TODO] Replace with a realistic call using fake data
const result = {module}('hello')
console.log(`Result: ${{result}}`)
'''



_TS_SRC = '''\
/**
 * {name}
 */
export function {module}(value: string): string {{
  return value
}}
'''

_TS_TEST = '''\
import {{ {module} }} from '../src/{module}'

test('placeholder', () => {{
  // TODO: replace with real tests
  expect({module}('hello')).toBe('hello')
}})
'''

_TS_EXAMPLE = '''\
/**
 * Example usage of {name}.
 *
 * This file must run and exit cleanly with no user input, no network calls,
 * and no external services or API keys. Use fake/hardcoded data to demonstrate the API.
 * The widget's own declared dependencies are fine - the validator installs them first.
 */
import {{ {module} }} from '../src/{module}'

// [TODO] Replace with a realistic call using fake data
const result = {module}('hello')
console.log(`Result: ${{result}}`)
'''

_REACT_DEV_DEPS = {
    "@vitejs/plugin-react": "^4.0.0",
    "@testing-library/react": "^14.0.0",
    "jsdom": "^24.0.0",
    "esbuild": "^0.20.0",
}

_COVERAGE_THRESHOLD = 80


_VITEST_FALLBACK = """\
export default {
  test: {
    include: ['tests/test_*.*'],
    globals: true,
    coverage: {
      include: ['src/**'],
    },
  }
}
"""

_VITEST_FRONTEND = """\
export default {
  test: {
    include: ['tests/test_*.*'],
    environment: 'happy-dom',
    globals: true,
    coverage: {
      include: ['src/**'],
    },
  }
}
"""


class JavaScriptEngine(LanguageEngine):
    name = "javascript"
    aliases = ["js"]
    validation_version = 1
    file_ext = "js"
    toolchain = {
        "node": "Install Node.js 18+ - nodejs.org",
        "npx": "Reinstall Node.js - npx ships with it",
    }
    scanner_runner = ["node"]
    scanner_messages = {
        "console_log": "console.log() found in src/ - remove debug output before checkin:",
        "process_exit": "process.exit() found in src/ - widgets must not exit the process:",
        "eval": "eval() found in src/ - dynamic code execution is a security risk:",
    }
    import_pattern = r"from\s+['\"]\.\.?/src/"
    manifest_patterns = ["package.json"]

    def runtime_version(self) -> str | None:
        try:
            res = self._run(["node", "--version"], cwd=".", timeout=10)
            if res.returncode == 0:
                ver = res.stdout.strip().lstrip("v")
                return f"node {ver}"
        except Exception:
            pass
        return None

    def check_optional(self) -> list[tuple[str, bool, str]]:
        import subprocess
        checks = []
        try:
            r = subprocess.run(
                ["npx", "playwright", "--version"],
                capture_output=True, timeout=15,
            )
            installed = r.returncode == 0
        except Exception:
            installed = False
        if installed:
            checks.append(("playwright", True, "browser widget validation available"))
        else:
            checks.append(("playwright", False,
                           "not installed - browser widgets (Canvas/WebGL) can't be validated"))
        return checks

    def scaffold(self, target_dir, module_name, display_name, **kwargs):
        domain = kwargs.get("domain", "")
        is_frontend = domain == "frontend"

        dev_deps = {
            "vitest": "^1.0.0",
            "@vitest/coverage-v8": "^1.0.0",
        }
        if is_frontend:
            dev_deps["happy-dom"] = "^15.0.0"

        pkg = {
            "name": os.path.basename(target_dir),
            "version": "1.0.0",
            "type": "module",
            "dependencies": {},
            "devDependencies": dev_deps,
        }
        with open(os.path.join(target_dir, "package.json"), "w") as f:
            json.dump(pkg, f, indent=2)

        with open(os.path.join(target_dir, "src", f"{module_name}.js"), "w") as f:
            f.write(_JS_PLAIN_SRC.format(name=display_name, module=module_name))
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.js"), "w") as f:
            f.write(_JS_PLAIN_TEST.format(module=module_name))
        with open(os.path.join(target_dir, "examples", "example_usage.js"), "w") as f:
            f.write(_JS_PLAIN_EXAMPLE.format(name=display_name, module=module_name))

        # Frontend gets a vitest config with happy-dom environment
        if is_frontend:
            with open(os.path.join(target_dir, "vitest.config.js"), "w") as f:
                f.write(_VITEST_FRONTEND)

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

    scanner_warning_messages = {
        "abs_path": "Absolute paths found in src/ - widgets must be portable:",
        "credential": "Possible credentials found in src/ - remove before checkin:",
        "hardcoded_url": "Hardcoded URLs found in src/ - consider making these configurable:",
        "hardcoded_ip": "Hardcoded IPs found in src/ - consider making these configurable:",
        "hardcoded_value": "Hardcoded values found in src/ - consider making these configurable:",
        "env_var": "Environment variable access found in src/ - verify it's not project-specific:",
        "unlisted_import": "Unlisted imports found in src/ - add to dependencies or remove:",
        "sleep": "Sleep/blocking calls found - widgets must not block the caller:",
        "risky_import": "Node.js I/O or network imports found in src/ - ensure no hardcoded paths, URLs, or commands:",
    }

    def validate_widget(self, path: str, dependencies: list) -> dict:
        """Scan src/ for contamination using native JS scanner."""
        errors = []

        # Native scanner - handles strings, comments, template literals
        src_dir = os.path.join(path, "src")
        src_files = []
        if os.path.isdir(src_dir):
            for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
                src_files.extend(_glob.glob(os.path.join(src_dir, "**", ext), recursive=True))

        scanner = os.path.join(os.path.dirname(__file__), "scanners", "js_scanner.js")
        scan_errors, _, _ = self._run_native_scanner(
            scanner_path=scanner,
            runner=self.scanner_runner,
            src_files=src_files,
            cwd=path,
            finding_messages=self.scanner_messages,
        )
        errors.extend(scan_errors)

        errors.extend(self._check_dep_pinning(dependencies))

        if errors:
            return self._fail("\n".join(errors))
        return self._ok()

    def _collect_source_files(self, path: str) -> tuple[list[str], list[str], list[str]]:
        """JS/TS uses multiple extensions."""
        src_files, test_files, example_files = [], [], []
        for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
            src_files.extend(_glob.glob(os.path.join(path, "src", "**", ext), recursive=True))
            test_files.extend(_glob.glob(os.path.join(path, "tests", "**", ext), recursive=True))
            example_files.extend(_glob.glob(os.path.join(path, "examples", "**", ext), recursive=True))
        return src_files, test_files, example_files

    def scan_contamination(self, path: str, widget: dict) -> dict:
        """JS contamination: native scanner on src + test + example files."""
        src_files, test_files, example_files = self._collect_source_files(path)
        all_files = src_files + test_files + example_files
        scanner = os.path.join(os.path.dirname(__file__), "scanners", "js_scanner.js")
        scan_errors, scan_warnings, scan_blocks = self._run_native_scanner(
            scanner_path=scanner,
            runner=self.scanner_runner,
            src_files=all_files,
            cwd=path,
            finding_messages=self.scanner_messages,
        )

        return {"blocks": scan_blocks + scan_errors, "warnings": scan_warnings}

    # ------------------------------------------------------------------ interface

    def find_test_files(self, path: str) -> list[str]:
        files = []
        for ext in ("js", "jsx", "ts", "tsx"):
            files.extend(_glob.glob(os.path.join(path, "tests", "**", f"test_*.{ext}"), recursive=True))
        return files

    def example_filename(self, path: str = "") -> str:
        if path and self._has_react(self._read_deps(path)):
            return "example_usage.jsx"
        return "example_usage.js"

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
                "devDependencies": {"vitest": "^1.0.0", "@vitest/coverage-v8": "^1.0.0"},
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

        # Per-validation npm cache so install never writes to ~/.npm. Required
        # for sandboxed environments (Codex, restricted devcontainers) where
        # $HOME is read-only. Cleaned up in cleanup().
        npm_cache = tempfile.mkdtemp(prefix="cartograph_npm_")
        self._npm_cache_dir = npm_cache
        res = self._run(
            ["npm", "install", "--silent", "--cache", npm_cache],
            cwd=path,
            timeout=120,
        )
        if res.returncode != 0:
            output = (res.stderr or res.stdout or "").strip()
            raise RuntimeError(
                "Failed to install npm dependencies."
                + (f"\n{output[:2000]}" if output else "")
            )

    # ------------------------------------------------------------------ tests

    @staticmethod
    def _has_vitest_config(path: str) -> bool:
        """Check if the widget has its own vitest config."""
        for name in ("vitest.config.js", "vitest.config.ts", "vitest.config.mjs",
                      "vitest.config.mts"):
            if os.path.exists(os.path.join(path, name)):
                return True
        return False

    def run_tests(self, path: str) -> dict:
        t = _COVERAGE_THRESHOLD
        cmd = [
            "npx", "vitest", "run", "--coverage",
            f"--coverage.thresholds.statements={t}",
            f"--coverage.thresholds.branches={t}",
            f"--coverage.thresholds.functions={t}",
            f"--coverage.thresholds.lines={t}",
        ]

        # If no vitest config exists, provide a minimal fallback
        fallback_config = None
        if not self._has_vitest_config(path):
            fallback_config = os.path.join(path, f"vitest.config.{uuid.uuid4().hex}.js")
            with open(fallback_config, "w") as f:
                f.write(_VITEST_FALLBACK)
            cmd.extend(["--config", os.path.basename(fallback_config)])

        try:
            res = self._run(cmd, cwd=path, timeout=120)
        finally:
            if fallback_config and os.path.exists(fallback_config):
                os.remove(fallback_config)

        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    # ------------------------------------------------------------------ example

    def _run_example_with_runner(self, path: str, runner_cmd: list) -> dict:
        """Run an example file, using esbuild for React projects."""
        example_path = os.path.join(path, "examples", self.example_filename(path))

        if not self._has_react(self._read_deps(path)):
            res = self._run(runner_cmd + [example_path], cwd=path, timeout=30)
            if res.returncode != 0:
                return self._fail(res.stderr or res.stdout)
            return self._ok()

        # React: bundle with esbuild, run with node
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

    def run_example(self, path: str) -> dict:
        return self._run_example_with_runner(path, ["node"])

    # ------------------------------------------------------------------ cleanup

    def cleanup(self, path: str) -> None:
        for dirname in ("node_modules", "coverage"):
            d = os.path.join(path, dirname)
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
        npm_cache = getattr(self, "_npm_cache_dir", None)
        if npm_cache and os.path.exists(npm_cache):
            shutil.rmtree(npm_cache, ignore_errors=True)
            log.debug("Removed isolated npm cache: %s", npm_cache)
        self._npm_cache_dir = None


class TypeScriptEngine(JavaScriptEngine):
    name = "typescript"
    aliases = ["ts"]
    file_ext = "ts"

    def scaffold(self, target_dir, module_name, display_name, **kwargs):
        # Let JS scaffold handle package.json and vitest config (domain branching for happy-dom)
        super().scaffold(target_dir, module_name, display_name, **kwargs)
        # Overwrite JS source files with TypeScript equivalents
        os.remove(os.path.join(target_dir, "src", f"{module_name}.js"))
        os.remove(os.path.join(target_dir, "tests", f"test_{module_name}.js"))
        os.remove(os.path.join(target_dir, "examples", "example_usage.js"))
        with open(os.path.join(target_dir, "src", f"{module_name}.ts"), "w") as f:
            f.write(_TS_SRC.format(name=display_name, module=module_name))
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.ts"), "w") as f:
            f.write(_TS_TEST.format(module=module_name))
        with open(os.path.join(target_dir, "examples", "example_usage.ts"), "w") as f:
            f.write(_TS_EXAMPLE.format(name=display_name, module=module_name))

    def example_filename(self, path: str = "") -> str:
        if path and self._has_react(self._read_deps(path)):
            return "example_usage.tsx"
        return "example_usage.ts"

    def run_example(self, path: str) -> dict:
        return self._run_example_with_runner(path, ["npx", "tsx"])
