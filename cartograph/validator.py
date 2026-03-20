"""
Widget validation against Gold Standards.

validate_item() checks directory structure, manifest schema, tests, examples,
language-specific rules, and implementation uniqueness before checkin.
"""

import glob
import json
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger("cartograph")


VALID_DOMAINS = frozenset([
    "backend", "data", "ml", "security", "infra", "frontend", "universal"
])


def validate_item(carto, path):
    """Validate a widget directory before checkin."""
    checklist = []
    errors = []

    def check(description, passed, error_detail=None):
        checklist.append(f"{'✅' if passed else '❌'} {description}")
        if not passed and error_detail:
            errors.append(error_detail)
        return passed

    # 1. Path exists
    if not check("Path exists", os.path.exists(path), f"Path not found: {path}"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Path not found: {path}"}

    # 2. widget.json exists
    manifest_path = os.path.join(path, "widget.json")
    if not os.path.exists(manifest_path):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Missing widget.json"}

    check("widget.json exists", True)

    # 3. Valid JSON, no TODOs
    try:
        content = open(manifest_path).read()
        data = json.loads(content)
        check("widget.json is valid JSON", True)
    except (OSError, json.JSONDecodeError) as e:
        check("widget.json is valid JSON", False, str(e))
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Invalid JSON: {e}"}

    todo_count = content.count("[TODO]")
    if not check("No [TODO] placeholders", todo_count == 0,
                 f"Found {todo_count} [TODO] placeholder(s) — fill them in"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Replace all [TODO] placeholders in widget.json"}

    # 4. Required meta fields
    meta = data.get("meta", {})
    for field in ("id", "name", "domain"):
        if not check(f"meta.{field} present", bool(meta.get(field)),
                     f"Missing required field meta.{field}"):
            _print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"meta.{field} is required"}

    # 5. Domain is a known value
    domain = meta.get("domain", "").lower()
    valid_domains = sorted(VALID_DOMAINS)
    if not check(f"meta.domain is valid ({domain})",
                 domain in VALID_DOMAINS,
                 f"'{domain}' is not a valid domain. Choose one of: {', '.join(valid_domains)}"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error",
                "message": f"Invalid domain '{domain}'. Valid domains: {', '.join(valid_domains)}"}

    # 6. tech_stack
    tech_stack = data.get("tech_stack", {})
    if not check("tech_stack.language present", bool(tech_stack.get("language")),
                 "Missing tech_stack.language"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Missing tech_stack.language"}

    if not check("tech_stack.dependencies present", "dependencies" in tech_stack,
                 "Missing tech_stack.dependencies (use [] if none)"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Missing tech_stack.dependencies (use [] if none)"}

    # 7. Required structure: src/, tests/, examples/
    for folder in ("src", "tests", "examples"):
        folder_path = os.path.join(path, folder)
        ok = os.path.isdir(folder_path) and bool(os.listdir(folder_path))
        if not check(f"{folder}/ exists and has files", ok,
                     f"{folder}/ is missing or empty"):
            _print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"{folder}/ is missing or empty"}

    # -- Resolve engine early so steps 7c/8 can use language-specific behaviour
    from .languages import get_engine
    from .engine import Cartograph, LIBRARY_PATH
    language = tech_stack.get("language", "python").lower()
    dependencies = tech_stack.get("dependencies", [])
    engine = get_engine(language)

    # 6b. No widget-on-widget dependencies
    try:
        library_ids = {w["id"] for w in Cartograph(LIBRARY_PATH).widgets}
    except Exception:
        library_ids = set()
    widget_deps = [
        d["name"] if isinstance(d, dict) else str(d)
        for d in dependencies
        if (d["name"] if isinstance(d, dict) else str(d)) in library_ids
    ]
    if not check("No widget-on-widget dependencies", not widget_deps,
                 f"Dependencies cannot be other widgets: {', '.join(widget_deps)}. "
                 "Copy the needed logic into src/ instead."):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error",
                "message": f"Widget depends on other widgets ({', '.join(widget_deps)}). "
                           "Widgets must be self-contained — copy the logic into src/ instead."}

    if engine is None:
        from .languages.registry import supported_languages
        langs = ", ".join(supported_languages())
        msg = f"Unknown language '{language}'. Supported: {langs}."
        check(f"Language '{language}' recognised", False, msg)
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": msg}

    if not engine.supported:
        from .languages.registry import supported_languages
        langs = ", ".join(supported_languages())
        msg = f"'{language}' is not supported for validation. Supported: {langs}."
        check(f"Language '{language}' supported", False, msg)
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": msg}

    # 7b. src/__init__.py imports cleanly (Python only)
    init_path = os.path.join(path, "src", "__init__.py")
    if language == "python" and os.path.exists(init_path):
        init_result = subprocess.run(
            [sys.executable, "-c", "import src"],
            cwd=path, capture_output=True, text=True, timeout=10
        )
        init_ok = init_result.returncode == 0
        init_err = (init_result.stderr or "").strip()
        if not check("src/__init__.py imports cleanly", init_ok, init_err):
            _print_checklist(checklist, errors, failed=True)
            return {"status": "error",
                    "message": "src/__init__.py has import errors.",
                    "test_output": init_err}

    # 7c. Example file exists and has no TODOs (execution deferred until after install)
    # Note: examples/usage_hint.* files are intentionally not executed — they are
    # real code from the author that requires a browser/app context to run
    # (see library_config.json general_notes for the full convention).
    example_file = engine.example_filename(path)
    example_path = os.path.join(path, "examples", example_file)
    if not check(f"examples/{example_file} exists", os.path.exists(example_path),
                 f"Missing examples/{example_file}"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Missing examples/{example_file}"}

    example_content = open(example_path).read()
    example_todos = example_content.count("[TODO]")
    if not check(f"No [TODO] in {example_file}", example_todos == 0,
                 f"Found {example_todos} [TODO] placeholder(s) in examples/{example_file} — write real example code"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Replace [TODO] placeholders in examples/{example_file}"}

    # 7d. Example imports at least one thing from src/
    if language == "python":
        imports_src = bool(re.search(r'from src\.|import src\.', example_content))
    else:
        imports_src = bool(re.search(r"from\s+['\"]\.\.?/src/", example_content))
    if not check(f"{example_file} imports from src/", imports_src,
                 f"examples/{example_file} does not import anything from src/ — the example must use the widget"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": (
            f"examples/{example_file} must import from src/\n\n"
            f"Expected pattern:\n"
            f"  sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
            f"  from src.mymodule import MyClass"
        )}

    # 8. Test files follow naming convention
    test_files = engine.find_test_files(path)
    if not check(f"Test files found ({len(test_files)})", len(test_files) > 0,
                 f"No test files found in tests/ for language '{language}'"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"No test files found in tests/ — name them test_*.py (Python) or test_*.js/jsx (JavaScript)"}

    # 9. Language checks, install deps, run example, run tests
    log.debug("Running language checks...")
    lang_check = engine.validate_widget(path, dependencies)
    if not check("Language checks pass", lang_check["passed"],
                 lang_check.get("error", "")):
        _print_checklist(checklist, errors, failed=True,
                          test_output=lang_check.get("error"))
        return {"status": "error", "message": lang_check.get("error", "Language checks failed"),
                "test_output": lang_check.get("error", "")}

    log.debug("Installing dependencies...")
    try:
        engine.install_deps(path, dependencies)
        check("Dependencies installed", True)
    except Exception as e:
        check("Dependencies installed", False, str(e))
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Dependency install failed: {e}"}

    log.debug("Running example...")
    example_result = engine.run_example(path)
    example_err = example_result.get("error", "")
    if not check(f"{example_file} runs cleanly", example_result["passed"], example_err):
        _print_checklist(checklist, errors, failed=True, test_output=example_err)
        return {"status": "error", "message": f"{example_file} failed to run.",
                "test_output": example_err[:500]}

    log.debug("Running tests...")
    result = engine.run_tests(path)
    test_error = result.get("error", "")
    if not check("All tests pass", result["passed"], test_error):
        _print_checklist(checklist, errors, failed=True, test_output=test_error)
        return {"status": "error", "message": "Tests failed. Fix before checkin.",
                "test_output": test_error[:3000]}

    # 10. Uniqueness check
    current_hash = carto._calculate_implementation_hash(path)
    duplicate = next((w for w in carto.widgets
                      if w.get("implementation_hash") == current_hash
                      and w["id"] != meta.get("id")), None)
    check("Implementation is unique",
          duplicate is None,
          f"Identical code already exists: {duplicate['id']}" if duplicate else None)

    _print_checklist(checklist, errors, failed=False)

    # Write a stamp so checkin can skip re-validation if nothing changes
    from .validation_stamp import write_stamp
    write_stamp(path, language, engine)

    return {"status": "success", "message": "Widget is valid"}


def _print_checklist(checklist, errors, failed, test_output=None):
    """Log validation results."""
    status = "FAILED" if failed else "PASSED"
    log.info("Validation %s (%d checks)", status, len(checklist))
    for item in checklist:
        log.debug("  %s", item)
    for error in errors:
        log.debug("  Error: %s", error)
    if test_output:
        log.debug("  Test output: %s", test_output[:500])
