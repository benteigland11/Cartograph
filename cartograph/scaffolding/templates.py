"""
Language-specific file templates for widget scaffolding.

Each function writes starter src/, tests/, and examples/ files for a given language.
None of these need the Cartograph instance — they just write files to disk.
"""

import os


def python(target_dir, module_name, display_name, **_):
    with open(os.path.join(target_dir, "src", "__init__.py"), "w") as f:
        f.write(f"from .{module_name} import {module_name}\n")
        f.write(f"__all__ = ['{module_name}']\n")
    with open(os.path.join(target_dir, "src", f"{module_name}.py"), "w") as f:
        f.write(f'def {module_name}(value):\n    """{display_name}: process a value."""\n    return value\n')
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f"import sys, os\n"
            f"sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
            f"from src.{module_name} import {module_name}\n\n\n"
            f"def test_{module_name}_returns_value():\n"
            f"    assert {module_name}(42) == 42\n"
        )
    with open(os.path.join(target_dir, "examples", "example_usage.py"), "w") as f:
        f.write(
            f'"""\n'
            f"Example usage of {display_name}.\n\n"
            f"This file must run and exit cleanly with no user input, no network calls,\n"
            f"and no external dependencies. Use fake/hardcoded data to demonstrate the API.\n"
            f'"""\n'
            f"import sys, os\n"
            f"sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
            f"from src.{module_name} import {module_name}\n\n"
            f"# [TODO] Replace with a realistic call using fake data\n"
            f'result = {module_name}("hello")\n'
            f'print(f"Result: {{result}}")\n'
        )


# Registry: maps normalized language name → template function
TEMPLATES = {
    "python": python,
}
