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

    def scaffold(self, target_dir, module_name, display_name, **kwargs):
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
        _, scan_warnings, scan_blocks = self._run_native_scanner(
            scanner_path=scanner,
            runner=self.scanner_runner,
            src_files=all_files,
            cwd=path,
            finding_messages=self.scanner_messages,
        )

        return {"blocks": scan_blocks, "warnings": scan_warnings}

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
        nm = os.path.join(path, "node_modules")
        if os.path.exists(nm):
            shutil.rmtree(nm, ignore_errors=True)


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
