"""
Widget and blueprint scaffolding.

Usage:
    from scaffolding import create_widget, create_blueprint
"""

import json
import os
import re
import sys

from .templates import TEMPLATES

DEFAULT_INSTALL_DIR = "cartographer"

_LANG_VERSIONS = {
    "python": ">=3.8",
    "javascript": ">=ES2020",
    "typescript": ">=5.0",
    "go": ">=1.21",
    "rust": ">=1.70",
    "hip": "ROCm 6.x+",
    "cpp": "C++17",
    "c": "C11",
}

_COMPILER_DEFAULTS = {
    "hip": "hipcc",
    "cpp": "g++",
    "c": "gcc",
}


def create_widget(carto, item_id, language, name=None, domain="backend", tags=None,
                  target_dir=None, gpu_targets=None, widget_type=None):
    """Scaffold a new widget directory. Returns a status dict."""
    if tags is None:
        tags = []
    if gpu_targets is None:
        gpu_targets = []

    if not language:
        return {"status": "error", "message": "Language is required for widget creation."}

    normalized_lang = carto._normalize_language(language)

    if not name:
        name_base = item_id
        if name_base.endswith(f"-{normalized_lang}"):
            name_base = name_base[: -len(normalized_lang) - 1]
        name = name_base.replace("-", " ").title()

    if not target_dir:
        target_dir = os.path.join(os.getcwd(), DEFAULT_INSTALL_DIR, "widgets", item_id)

    if os.path.exists(target_dir):
        return {"status": "error", "message": f"Directory already exists: {target_dir}"}

    if not item_id.endswith(f"-{normalized_lang}"):
        item_id = f"{item_id}-{normalized_lang}"

    print(f"✨ Creating widget '{item_id}' ({language}) in {target_dir}...", file=sys.stderr)

    os.makedirs(target_dir)
    for d in ("src", "tests", "examples"):
        os.makedirs(os.path.join(target_dir, d))

    # Derive module name from item_id (strip category prefix + language suffix)
    parts = item_id.split("-")
    module_name = "_".join(parts[1:-1]) if len(parts) >= 3 else parts[0]
    module_name = re.sub(r"[^a-zA-Z0-9_]", "_", module_name)
    if module_name.startswith("test_") or module_name == "test":
        module_name = "mod_" + module_name

    # Build widget.json
    meta = {"id": item_id, "name": name, "version": "1.0.0", "type": "widget",
            "domain": domain, "tags": tags, "maturity": "beta"}
    if widget_type:
        meta["widget_type"] = widget_type

    tech_stack = {"language": normalized_lang,
                  "language_version": _LANG_VERSIONS.get(normalized_lang, ""),
                  "dependencies": []}
    if gpu_targets:
        tech_stack["gpu_targets"] = gpu_targets
    if normalized_lang in _COMPILER_DEFAULTS:
        tech_stack["compiler"] = _COMPILER_DEFAULTS[normalized_lang]

    manifest = {
        "meta": meta,
        "description": f"{name} widget",
        "tech_stack": tech_stack,
        "integration_guide": {"usage": f"Import and use the {name} module from src/",
                               "constraints": "None"},
        "depends_on": [],
    }
    with open(os.path.join(target_dir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Write language-specific files
    template_fn = TEMPLATES.get(normalized_lang, TEMPLATES["python"])
    template_fn(target_dir, module_name, name, item_id=item_id, gpu_targets=gpu_targets)

    print(f"✅ Created widget: {target_dir}", file=sys.stderr)
    return {"status": "success", "path": target_dir, "item_id": item_id, "language": normalized_lang}


def create_blueprint(carto, item_id, name=None, domain="backend", tags=None,
                     target_dir=None, composed_of=None):
    """Scaffold a new blueprint directory. Returns a status dict."""
    if tags is None:
        tags = []
    if composed_of is None:
        composed_of = []

    if not name:
        name = item_id.replace("-", " ").title()

    if not target_dir:
        target_dir = os.path.join(os.getcwd(), DEFAULT_INSTALL_DIR, "blueprints", item_id)

    if os.path.exists(target_dir):
        return {"status": "error", "message": f"Directory already exists: {target_dir}"}

    print(f"✨ Creating blueprint '{item_id}' in {target_dir}...", file=sys.stderr)

    for d in ("src", "examples", "widgets"):
        os.makedirs(os.path.join(target_dir, d), exist_ok=True)

    # Pin composed_of to current library versions
    pinned = []
    for wid in composed_of:
        widget = next((w for w in carto.widgets if w["id"] == wid), None)
        pinned.append({"id": wid, "version": widget.get("version", "1.0.0") if widget else None})

    manifest = {
        "meta": {"id": item_id, "name": name, "version": "1.0.0", "type": "blueprint",
                 "domain": domain, "tags": tags, "maturity": "beta"},
        "composed_of": pinned,
        "configuration": {},
        "description": f"{name} blueprint",
        "integration_guide": {
            "pattern": "dependency_injection",
            "usage": "Install widgets into this blueprint, then wire them together in src/",
            "runtime_wiring": {
                "description": "Wire up the workflow after installation",
                "prerequisites": {"environment": [], "database": [], "application": []},
                "steps": [],
            },
        },
    }
    with open(os.path.join(target_dir, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(target_dir, "examples", "basic_usage.md"), "w") as f:
        f.write(f"# {name} Blueprint\n\n## Usage\n\n"
                "1. Install widgets using `cartographer_install` with the `blueprint` parameter.\n"
                "2. Wire the widgets together in `src/`.\n"
                "3. Check in the self-contained blueprint.\n")

    class_name = name.replace(" ", "")
    with open(os.path.join(target_dir, "src", "workflow.py"), "w") as f:
        f.write(f'"""\n{name} Blueprint — wire your installed widgets here.\n"""\n\n\nclass {class_name}:\n    pass\n')

    print(f"✅ Created blueprint: {target_dir}", file=sys.stderr)
    return {"status": "success", "path": target_dir, "item_id": item_id}
