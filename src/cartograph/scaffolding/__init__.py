"""
Widget scaffolding.

Usage:
    from cartograph.scaffolding import create_widget
"""

import json
import logging
import os
import re
import sys

log = logging.getLogger("cartograph")


from cartograph.engine import DEFAULT_INSTALL_DIR, python_dir_name

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "library_config.json")

def _library_notes(language: str, domain: str = "") -> dict:
    """Load general + language-specific + domain-specific notes from library_config.json."""
    try:
        with open(_CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        return {}
    notes = {
        "general": cfg.get("general_notes", ""),
        "language": cfg.get("language_notes", {}).get(language.lower(), ""),
    }
    domain_note = cfg.get("domain_notes", {}).get(domain.lower(), "")
    if domain_note:
        notes["domain"] = domain_note
    return notes

_LANG_VERSIONS = {
    "python": ">=3.10",
}

_COMPILER_DEFAULTS = {}

_VALID_DOMAINS = {"backend", "data", "ml", "security", "infra", "frontend", "universal"}


def create_widget(carto, item_id, language, name=None, domain=None, tags=None,
                  target_dir=None, gpu_targets=None, widget_type=None):
    """Scaffold a new widget directory. Returns a status dict."""
    if tags is None:
        tags = []
    if gpu_targets is None:
        gpu_targets = []

    if not language:
        return {"status": "error", "message": "Language is required for widget creation."}

    normalized_lang = carto._normalize_language(language)

    # Strip language suffix to get the base id for name/domain inference
    name_base = item_id
    if name_base.endswith(f"-{normalized_lang}"):
        name_base = name_base[: -len(normalized_lang) - 1]

    # Derive display name from base parts
    base_parts = name_base.split("-")
    if domain is None:
        domain = "backend"

    # Strip domain prefix from display name if it matches
    if not name:
        display_parts = base_parts[1:] if base_parts[0] in _VALID_DOMAINS else base_parts
        name = " ".join(display_parts).title() if display_parts else name_base.replace("-", " ").title()

    if not item_id.endswith(f"-{normalized_lang}"):
        item_id = f"{item_id}-{normalized_lang}"

    if not target_dir:
        target_dir = os.getcwd()

    # Always place under <project_root>/cartograph/<widget_id>
    target_dir = os.path.join(target_dir, DEFAULT_INSTALL_DIR, python_dir_name(item_id))

    if os.path.exists(target_dir):
        return {"status": "error", "message": f"Directory already exists: {target_dir}"}

    log.info("Creating widget '%s' (%s) in %s", item_id, language, target_dir)

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
    meta = {"id": item_id, "name": name, "version": "1.0.0", "domain": domain, "tags": tags or ["[TODO: add 3-5 tags]"]}

    tech_stack = {"language": normalized_lang, "dependencies": []}

    manifest = {
        "meta": meta,
        "description": f"[TODO] Describe what {name} does",
        "tech_stack": tech_stack,
        "library_notes": _library_notes(normalized_lang, domain),
    }
    with open(os.path.join(target_dir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Write language-specific files from engine scaffold
    from cartograph.languages import get_engine
    from cartograph.languages.base import LanguageEngine as _BaseEngine
    engine = get_engine(normalized_lang)
    if engine and engine.__class__.scaffold is not _BaseEngine.scaffold:
        engine.scaffold(target_dir, module_name, name, item_id=item_id, gpu_targets=gpu_targets)
    else:
        return {"status": "error", "message": f"No scaffold template for language '{normalized_lang}'"}

    log.info("Created widget: %s", target_dir)
    return {"status": "success", "path": target_dir, "item_id": item_id, "language": normalized_lang}
