"""C / C++ language engine — supports CMake + CTest and plain Makefile."""

import os
import shutil

from .base import LanguageEngine


class CppEngine(LanguageEngine):
    name = "cpp"

    def install_deps(self, path: str, dependencies: list) -> None:
        # System-level deps (cmake, make) are assumed installed.
        pass

    def run_tests(self, path: str) -> dict:
        if os.path.exists(os.path.join(path, "CMakeLists.txt")):
            return self._run_cmake(path)
        if os.path.exists(os.path.join(path, "Makefile")):
            return self._run_make(path)
        return self._fail("No CMakeLists.txt or Makefile found.")

    def _run_cmake(self, path: str) -> dict:
        print("🛠️  Found CMakeLists.txt — running cmake + ctest...")
        build_dir = os.path.join(path, "build_temp")
        os.makedirs(build_dir, exist_ok=True)
        try:
            conf = self._run(["cmake", ".."], cwd=build_dir, timeout=30)
            if conf.returncode != 0:
                return self._fail(f"CMake configure failed: {conf.stderr}")
            res = self._run(
                ["ctest", "--output-on-failure"], cwd=build_dir, timeout=60
            )
            if res.returncode != 0:
                return self._fail(res.stdout or res.stderr)
            return self._ok()
        except FileNotFoundError:
            return self._fail("CMake/CTest not found.")
        finally:
            shutil.rmtree(build_dir, ignore_errors=True)

    def _run_make(self, path: str) -> dict:
        print("📜 Found Makefile — running make test...")
        try:
            res = self._run(["make", "test"], cwd=path, timeout=60)
        except FileNotFoundError:
            return self._fail("Make not found.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()


# C shares the same build tooling as C++
class CEngine(CppEngine):
    name = "c"
