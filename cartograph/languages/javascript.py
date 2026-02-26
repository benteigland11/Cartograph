"""JavaScript / TypeScript language engine — uses npm + vitest."""

import json
import os

from .base import LanguageEngine, log


class JavaScriptEngine(LanguageEngine):
    name = "javascript"

    def install_deps(self, path: str, dependencies: list) -> None:
        log.debug("Installing %d npm package(s) (+ vitest for testing)...", len(dependencies))
        package_json_path = os.path.join(path, "package.json")

        if not os.path.exists(package_json_path):
            # Create a temporary package.json — caller is responsible for cleanup
            pkg = {
                "name": os.path.basename(path),
                "version": "1.0.0",
                "type": "module",
                "dependencies": {},
                "devDependencies": {"vitest": "^1.0.0"},
            }
            for dep in dependencies:
                name = dep if isinstance(dep, str) else dep.get("name", "")
                ver = "*" if isinstance(dep, str) else dep.get("version", "*")
                if name:
                    pkg["dependencies"][name] = ver
            with open(package_json_path, "w") as f:
                json.dump(pkg, f, indent=2)
        else:
            # Ensure vitest is listed
            with open(package_json_path, "r") as f:
                pkg = json.load(f)
            dev = pkg.setdefault("devDependencies", {})
            if "vitest" not in dev and "vitest" not in pkg.get("dependencies", {}):
                dev["vitest"] = "^1.0.0"
                with open(package_json_path, "w") as f:
                    json.dump(pkg, f, indent=2)

        self._run(["npm", "install", "--silent"], cwd=path, timeout=120)

    def run_tests(self, path: str) -> dict:
        config_path = os.path.join(path, "vitest.config.temp.js")
        try:
            with open(config_path, "w") as f:
                f.write("export default { test: { include: ['tests/test_*.*'] } }\n")
            res = self._run(
                ["npx", "vitest", "run", "--config", "vitest.config.temp.js"],
                cwd=path,
                timeout=60,
            )
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()

    def cleanup(self, path: str) -> None:
        """Remove node_modules and any temp package.json created during install."""
        import shutil
        nm = os.path.join(path, "node_modules")
        if os.path.exists(nm):
            shutil.rmtree(nm, ignore_errors=True)


# TypeScript reuses the same engine
class TypeScriptEngine(JavaScriptEngine):
    name = "typescript"
