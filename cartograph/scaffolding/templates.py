"""
Language-specific file templates for widget scaffolding.

Each function writes starter src/, tests/, and examples/ files for a given language.
None of these need the Cartograph instance — they just write files to disk.
"""

import json
import os


def python(target_dir, module_name, display_name, **_):
    with open(os.path.join(target_dir, "src", "__init__.py"), "w") as f:
        f.write("# Package marker — add explicit exports here once the public API is stable.\n")
    with open(os.path.join(target_dir, "src", f"{module_name}.py"), "w") as f:
        f.write(f'def {module_name}(value):\n    """{display_name}: process a value."""\n    return value\n')
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f"def test_placeholder():\n"
            f"    # TODO: replace with real tests\n"
            f"    pass\n"
        )
    with open(os.path.join(target_dir, "examples", "example_usage.py"), "w") as f:
        f.write(
            f'"""\n'
            f"Example usage of {display_name}.\n\n"
            f"This file must run and exit cleanly with no user input, no network calls,\n"
            f"and no external services or API keys. Use fake/hardcoded data to demonstrate the API.\n"
            f"The widget's own declared dependencies are fine — the validator installs them first.\n"
            f'"""\n'
            f"import sys, os\n"
            f"sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
            f"from src.{module_name} import {module_name}\n\n"
            f"# [TODO] Replace with a realistic call using fake data\n"
            f'result = {module_name}("hello")\n'
            f'print(f"Result: {{result}}")\n'
        )


def javascript(target_dir, module_name, display_name, **kwargs):
    # PascalCase component name from snake_case module_name
    component_name = "".join(w.capitalize() for w in module_name.split("_"))

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

    with open(os.path.join(target_dir, "src", f"{component_name}.jsx"), "w") as f:
        f.write(
            f"/**\n"
            f" * {display_name}\n"
            f" */\n"
            f"export function {component_name}({{ children }}) {{\n"
            f"  return (\n"
            f"    <div className=\"{module_name.replace('_', '-')}\">\n"
            f"      {{children}}\n"
            f"    </div>\n"
            f"  )\n"
            f"}}\n"
        )

    with open(os.path.join(target_dir, "tests", f"test_{component_name}.jsx"), "w") as f:
        f.write(
            f"import {{ render, screen }} from '@testing-library/react'\n"
            f"import {{ {component_name} }} from '../src/{component_name}.jsx'\n\n"
            f"test('renders children', () => {{\n"
            f"  render(<{component_name}>Hello</{component_name}>)\n"
            f"  expect(screen.getByText('Hello')).toBeTruthy()\n"
            f"}})\n"
        )

    with open(os.path.join(target_dir, "examples", "example_usage.jsx"), "w") as f:
        f.write(
            f"/**\n"
            f" * Example usage of {display_name}.\n"
            f" *\n"
            f" * Renders via react-dom/server — no browser needed.\n"
            f" * Use fake/hardcoded props to demonstrate the component API.\n"
            f" */\n"
            f"import {{ renderToString }} from 'react-dom/server'\n"
            f"import {{ {component_name} }} from '../src/{component_name}.jsx'\n\n"
            f"// [TODO] Replace with a realistic call using fake props\n"
            f"const html = renderToString(\n"
            f"  <{component_name}>Example content</{component_name}>\n"
            f")\n"
            f"console.log(html)\n"
        )

    with open(os.path.join(target_dir, "examples", "usage_hint.jsx"), "w") as f:
        f.write(
            f"/**\n"
            f" * Usage hint for {display_name} — real integration code, not pipeline-validated.\n"
            f" *\n"
            f" * Show how this component fits into a real app: routing, providers, layout, etc.\n"
            f" * This file is a courtesy from the author and is not executed by Cartograph.\n"
            f" * Fill it in or delete it — it has no effect on validation or checkin.\n"
            f" */\n\n"
            f"// [TODO] Show a real-world integration — e.g. inside a router, a page, a provider tree\n"
            f"// import {{ {component_name} }} from './cartograph/{component_name}/src/{component_name}.jsx'\n"
            f"//\n"
            f"// export function MyPage() {{\n"
            f"//   return <{component_name}>Hello</{component_name}>\n"
            f"// }}\n"
        )


# Registry: maps normalized language name → template function
TEMPLATES = {
    "python": python,
    "javascript": javascript,
}
