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

# React/frontend JS
_JS_SRC = '''\
/**
 * {name}
 */
export function {component}({{ children }}) {{
  return (
    <div className="{css_class}">
      {{children}}
    </div>
  )
}}
'''

_JS_TEST = '''\
import {{ render, screen }} from '@testing-library/react'
import {{ {component} }} from '../src/{component}.jsx'

test('renders children', () => {{
  render(<{component}>Hello</{component}>)
  expect(screen.getByText('Hello')).toBeTruthy()
}})
'''

_JS_EXAMPLE = '''\
/**
 * Example usage of {name}.
 *
 * Renders via react-dom/server - no browser needed.
 * Use fake/hardcoded props to demonstrate the component API.
 */
import {{ renderToString }} from 'react-dom/server'
import {{ {component} }} from '../src/{component}.jsx'

// [TODO] Replace with a realistic call using fake props
const html = renderToString(
  <{component}>Example content</{component}>
)
console.log(html)
'''

_JS_USAGE_HINT = '''\
/**
 * Usage hint for {name} - real integration code, not pipeline-validated.
 *
 * Show how this component fits into a real app: routing, providers, layout, etc.
 * This file is a courtesy from the author and is not executed by Cartograph.
 * Fill it in or delete it - it has no effect on validation or checkin.
 */

// [TODO] Show a real-world integration - e.g. inside a router, a page, a provider tree
// import {{ {component} }} from './cg/{component}/src/{component}.jsx'
//
// export function MyPage() {{
//   return <{component}>Hello</{component}>
// }}
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

_VITEST_PLAIN = """\
export default {
  test: {
    include: ['tests/test_*.*'],
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      thresholds: { statements: %d, branches: %d, functions: %d, lines: %d },
    },
  }
}
""" % (_COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD)

_VITEST_DOM = """\
export default {
  test: {
    include: ['tests/test_*.*'],
    environment: 'happy-dom',
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      thresholds: { statements: %d, branches: %d, functions: %d, lines: %d },
    },
  }
}
""" % (_COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD)

_VITEST_BROWSER = """\
import { defineConfig } from 'vitest/config'
export default defineConfig({
  test: {
    include: ['tests/test_*.*'],
    globals: true,
    browser: {
      enabled: true,
      provider: 'playwright',
      name: 'chromium',
      headless: true,
    },
    coverage: {
      provider: 'istanbul',
      include: ['src/**'],
      thresholds: { statements: %d, branches: %d, functions: %d, lines: %d },
    },
  }
})
""" % (_COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD)

_VITEST_REACT = """\
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    include: ['tests/test_*.*'],
    environment: 'jsdom',
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      thresholds: { statements: %d, branches: %d, functions: %d, lines: %d },
    },
  }
})
""" % (_COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD, _COVERAGE_THRESHOLD)


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
        "risky_import": "Risky imports found in src/ - flagged for review:",
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

        if domain == "frontend":
            self._scaffold_react(target_dir, module_name, display_name)
        else:
            self._scaffold_plain(target_dir, module_name, display_name)

    def _scaffold_plain(self, target_dir, module_name, display_name):
        with open(os.path.join(target_dir, "src", f"{module_name}.js"), "w") as f:
            f.write(_JS_PLAIN_SRC.format(name=display_name, module=module_name))
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.js"), "w") as f:
            f.write(_JS_PLAIN_TEST.format(module=module_name))
        with open(os.path.join(target_dir, "examples", "example_usage.js"), "w") as f:
            f.write(_JS_PLAIN_EXAMPLE.format(name=display_name, module=module_name))

    def _scaffold_react(self, target_dir, module_name, display_name):
        component = "".join(w.capitalize() for w in module_name.split("_"))
        css_class = module_name.replace("_", "-")

        # Pre-populate React deps in widget.json
        manifest_path = os.path.join(target_dir, "widget.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        manifest["tech_stack"]["dependencies"] = [
            "react>=18.0.0",
            "react-dom>=18.0.0",
        ]
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        with open(os.path.join(target_dir, "src", f"{component}.jsx"), "w") as f:
            f.write(_JS_SRC.format(name=display_name, component=component, css_class=css_class))
        with open(os.path.join(target_dir, "tests", f"test_{component}.jsx"), "w") as f:
            f.write(_JS_TEST.format(component=component))
        with open(os.path.join(target_dir, "examples", "example_usage.jsx"), "w") as f:
            f.write(_JS_EXAMPLE.format(name=display_name, component=component))
        with open(os.path.join(target_dir, "examples", "usage_hint.jsx"), "w") as f:
            f.write(_JS_USAGE_HINT.format(name=display_name, component=component))

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

    def _collect_source_files(self, path: str) -> tuple[list[str], list[str]]:
        """JS/TS uses multiple extensions."""
        src_files, test_files = [], []
        for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
            src_files.extend(_glob.glob(os.path.join(path, "src", "**", ext), recursive=True))
            test_files.extend(_glob.glob(os.path.join(path, "tests", "**", ext), recursive=True))
        return src_files, test_files

    def scan_contamination(self, path: str, widget: dict) -> dict:
        """JS contamination: native scanner on src + test files."""
        src_files, test_files = self._collect_source_files(path)
        all_files = src_files + test_files
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
        test_env = self._detect_test_env(path)
        is_browser = test_env == "browser"
        coverage_pkg = "@vitest/coverage-istanbul" if is_browser else "@vitest/coverage-v8"
        log.debug("Installing npm packages (react=%s, env=%s)...", has_react, test_env)

        package_json_path = os.path.join(path, "package.json")

        if not os.path.exists(package_json_path):
            pkg = {
                "name": os.path.basename(path),
                "version": "1.0.0",
                "type": "module",
                "dependencies": {},
                "devDependencies": {"vitest": "^1.0.0", coverage_pkg: "^1.0.0"},
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
            for tool, ver in (("vitest", "^1.0.0"), (coverage_pkg, "^1.0.0")):
                if tool not in dev and tool not in pkg.get("dependencies", {}):
                    dev[tool] = ver
                    changed = True
            if has_react:
                for dep_name, dep_ver in _REACT_DEV_DEPS.items():
                    if dep_name not in dev and dep_name not in pkg.get("dependencies", {}):
                        dev[dep_name] = dep_ver
                        changed = True
            if changed:
                with open(package_json_path, "w") as f:
                    json.dump(pkg, f, indent=2)

        res = self._run(["npm", "install", "--silent"], cwd=path, timeout=120)
        if res.returncode != 0:
            output = (res.stderr or res.stdout or "").strip()
            raise RuntimeError(
                "Failed to install npm dependencies."
                + (f"\n{output[:2000]}" if output else "")
            )

    # ------------------------------------------------------------------ tests

    @staticmethod
    def _detect_test_env(path: str) -> str:
        """Detect which test environment the widget needs from package.json.
        Returns 'browser', 'dom', or 'node'."""
        try:
            with open(os.path.join(path, "package.json")) as f:
                pkg = json.load(f)
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "@vitest/browser" in all_deps:
                return "browser"
            if "happy-dom" in all_deps or "jsdom" in all_deps:
                env = "happy-dom" if "happy-dom" in all_deps else "jsdom"
                return env
            return "node"
        except Exception:
            return "node"

    def run_tests(self, path: str) -> dict:
        has_react = self._has_react(self._read_deps(path))
        test_env = self._detect_test_env(path)
        config_path = os.path.join(path, f"vitest.config.{uuid.uuid4().hex}.js")
        try:
            if has_react:
                vitest_cfg = _VITEST_REACT
            elif test_env == "browser":
                vitest_cfg = _VITEST_BROWSER
            elif test_env in ("happy-dom", "jsdom"):
                vitest_cfg = _VITEST_DOM.replace("'happy-dom'", f"'{test_env}'")
            else:
                vitest_cfg = _VITEST_PLAIN
            with open(config_path, "w") as f:
                f.write(vitest_cfg)
            res = self._run(
                ["npx", "vitest", "run", "--coverage", "--config", os.path.basename(config_path)],
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


class TypeScriptEngine(JavaScriptEngine):
    name = "typescript"
    aliases = ["ts"]
    file_ext = "ts"

    def scaffold(self, target_dir, module_name, display_name, **_):
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
