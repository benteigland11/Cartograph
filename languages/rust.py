"""Rust language engine — uses cargo test."""

from .base import LanguageEngine


class RustEngine(LanguageEngine):
    name = "rust"

    def install_deps(self, path: str, dependencies: list) -> None:
        # Cargo.toml handles deps automatically; nothing to do here.
        pass

    def run_tests(self, path: str) -> dict:
        try:
            res = self._run(["cargo", "test"], cwd=path, timeout=120)
        except FileNotFoundError:
            return self._fail("Cargo not found — install Rust toolchain.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()
