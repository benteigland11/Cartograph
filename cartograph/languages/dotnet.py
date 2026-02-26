"""C# / .NET language engine — uses dotnet test."""

from .base import LanguageEngine


class DotNetEngine(LanguageEngine):
    name = "csharp"

    def install_deps(self, path: str, dependencies: list) -> None:
        # NuGet packages are restored automatically by dotnet test.
        pass

    def run_tests(self, path: str) -> dict:
        try:
            res = self._run(["dotnet", "test"], cwd=path, timeout=120)
        except FileNotFoundError:
            return self._fail(".NET SDK (dotnet) not found.")
        if res.returncode != 0:
            return self._fail(res.stderr or res.stdout)
        return self._ok()
