"""Go language engine — uses go mod tidy + go test."""

from .base import LanguageEngine, log


class GoEngine(LanguageEngine):
    name = "go"

    def install_deps(self, path: str, dependencies: list) -> None:
        if dependencies:
            log.debug("Running go mod tidy for %d Go package(s)...", len(dependencies))
        self._run(["go", "mod", "tidy"], cwd=path, timeout=60)

    def run_tests(self, path: str) -> dict:
        try:
            res = self._run(["go", "test", "./tests/..."], cwd=path, timeout=30)
        except FileNotFoundError:
            return self._fail("Go not found — install Go toolchain.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()
