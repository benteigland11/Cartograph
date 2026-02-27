"""
Widget validation against Gold Standards.

validate_item() checks directory structure, manifest schema, tests, examples,
language-specific rules, and implementation uniqueness before checkin.
"""

import glob
import json
import logging
import os
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
        return {"status": "error", "message": "Missing tech_stack.dependencies"}

    # 7. Required structure: src/, tests/, examples/
    for folder in ("src", "tests", "examples"):
        folder_path = os.path.join(path, folder)
        ok = os.path.isdir(folder_path) and bool(os.listdir(folder_path))
        if not check(f"{folder}/ exists and has files", ok,
                     f"{folder}/ is missing or empty"):
            _print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"{folder}/ is missing or empty"}

    # 7b. src/__init__.py imports cleanly
    init_path = os.path.join(path, "src", "__init__.py")
    if os.path.exists(init_path):
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

    # 7c. example_usage.py exists, has no TODOs, and runs cleanly
    example_path = os.path.join(path, "examples", "example_usage.py")
    if not check("examples/example_usage.py exists", os.path.exists(example_path),
                 "Missing examples/example_usage.py"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Missing examples/example_usage.py"}

    example_content = open(example_path).read()
    example_todos = example_content.count("[TODO]")
    if not check("No [TODO] in example_usage.py", example_todos == 0,
                 f"Found {example_todos} [TODO] placeholder(s) in example_usage.py — write real example code"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "Replace [TODO] placeholders in examples/example_usage.py"}

    example_result = subprocess.run(
        [sys.executable, "examples/example_usage.py"],
        cwd=path, capture_output=True, text=True, timeout=15
    )
    example_ok = example_result.returncode == 0
    example_err = (example_result.stderr or example_result.stdout)[:500]
    if not check("example_usage.py runs cleanly", example_ok, example_err):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "example_usage.py failed to run.",
                "test_output": example_err}

    # 8. Test files follow naming convention
    test_files = glob.glob(os.path.join(path, "tests", "test_*.py"))
    if not check(f"Test files found ({len(test_files)})", len(test_files) > 0,
                 "No test_*.py files found in tests/"):
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": "No test_*.py files found in tests/"}

    # 9. Install deps and run tests
    from .languages import get_engine
    language = tech_stack.get("language", "python").lower()
    dependencies = tech_stack.get("dependencies", [])
    engine = get_engine(language)

    if engine is None:
        check(f"Language '{language}' recognised", False, f"Unknown language '{language}'")
        _print_checklist(checklist, errors, failed=True)
        return {"status": "error", "message": f"Unknown language '{language}'"}

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
