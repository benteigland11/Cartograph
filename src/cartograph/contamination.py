"""
Contamination scanner - first stage of the widget pipeline.

Pipeline order: contamination -> validate -> checkin

Checks for project-specific contamination that would make a widget
non-portable. Each language engine provides its own scan_contamination()
method for language-specific detection on top of the generic checks.

Returns {"blocks": [...], "warnings": [...]}.
  - Blocks are hard failures (absolute paths, credentials). No override.
  - Warnings are quality concerns (hardcoded values, URLs, IPs, env vars,
    unlisted imports). Overridable with --override-warnings --override-reason.
"""

import json
import logging
import os

log = logging.getLogger("cartograph")


def scan_contamination(path: str) -> dict:
    """Run contamination scanning on a widget directory.

    Resolves the language engine from widget.json and delegates to
    engine.scan_contamination() which includes both generic and
    language-specific checks.
    """
    manifest_path = os.path.join(path, "widget.json")
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception:
        return {"blocks": [], "warnings": []}

    tech_stack = data.get("tech_stack", {})
    language = tech_stack.get("language", "python").lower()

    from .languages import get_engine
    engine = get_engine(language)
    if engine is None:
        # Unknown language - fall back to base engine for generic checks
        from .languages.base import LanguageEngine
        engine = LanguageEngine()

    return engine.scan_contamination(path, tech_stack)
