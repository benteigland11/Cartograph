"""JVM language engines — Maven (Java/Kotlin) and Gradle."""

from .base import LanguageEngine


class MavenEngine(LanguageEngine):
    name = "java"

    def install_deps(self, path: str, dependencies: list) -> None:
        # Maven resolves deps during test phase.
        pass

    def run_tests(self, path: str) -> dict:
        try:
            res = self._run(["mvn", "test"], cwd=path, timeout=120)
        except FileNotFoundError:
            return self._fail("Maven (mvn) not found.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()


class GradleEngine(LanguageEngine):
    name = "kotlin"

    def install_deps(self, path: str, dependencies: list) -> None:
        pass

    def run_tests(self, path: str) -> dict:
        try:
            res = self._run(["gradle", "test"], cwd=path, timeout=120)
        except FileNotFoundError:
            return self._fail("Gradle not found.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()
