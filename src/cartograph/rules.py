"""
Custom validation rules - user-defined checks that run during validation.

A rules file is a single script per language that receives the widget path
as its first argument and prints JSON to stdout:

    {"blocks": ["hard failure", ...], "warnings": ["soft warning", ...]}

Empty arrays or no output means all checks passed. Non-zero exit or
invalid JSON is treated as a block with the error details.

File locations (both run if both exist, project first):
    .cartograph/rules/rules.py       per-project rules
    <data_dir>/rules/rules.py        global rules

Fixed filenames per language:
    python      rules.py
    javascript  rules.js
    typescript  rules.js
    nim         rules.nim
"""

import json
import logging
import os
import subprocess
import sys

log = logging.getLogger("cartograph")

# Maps widget language -> (filename, runner command)
_LANGUAGE_RULES = {
    "python":     ("rules.py",  [sys.executable]),
    "javascript": ("rules.js",  ["node"]),
    "typescript": ("rules.js",  ["node"]),
    "nim":        ("rules.nim", ["nim", "r", "--hints:off"]),
    "angular":    ("rules.js",  ["node"]),
    "php":        ("rules.php", ["php"]),
}


def _rules_file_paths(language: str) -> list[dict]:
    """Return rules files that exist for this language.

    Returns list of {"path": str, "scope": "project"|"global"}.
    Project first, then global.
    """
    info = _LANGUAGE_RULES.get(language)
    if not info:
        return []

    filename, _ = info
    results = []

    # Per-project
    project_path = os.path.join(os.getcwd(), ".cartograph", "rules", filename)
    if os.path.isfile(project_path):
        results.append({"path": project_path, "scope": "project"})

    # Global
    from .engine import _user_data_dir
    global_path = os.path.join(_user_data_dir(), "rules", filename)
    if os.path.isfile(global_path):
        results.append({"path": global_path, "scope": "global"})

    return results


def find_rules() -> list[dict]:
    """Find all rules files across all languages.

    Returns list of {"language": str, "path": str, "scope": str}.
    """
    results = []
    seen_languages = set()
    for lang, (filename, _) in _LANGUAGE_RULES.items():
        if lang in seen_languages:
            continue
        seen_languages.add(lang)
        for entry in _rules_file_paths(lang):
            results.append({"language": lang, "filename": filename, **entry})
    return results


def _run_rules_file(path: str, widget_path: str, language: str) -> dict:
    """Execute a rules file and return {"blocks": [...], "warnings": [...]}.

    On error (bad exit code, invalid JSON, timeout), returns a clear
    error message explaining what went wrong and how to fix it.
    """
    info = _LANGUAGE_RULES.get(language)
    if not info:
        return {"blocks": [f"No runner configured for language '{language}'"], "warnings": []}

    _, runner = info
    cmd = runner + [path, os.path.abspath(widget_path)]
    scope = "project" if ".cartograph" in path else "global"
    label = f"{scope} rules ({os.path.basename(path)})"

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=widget_path,
        )
    except FileNotFoundError:
        return {
            "blocks": [f"{label}: runner not found ({runner[0]}). Is {language} installed?"],
            "warnings": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "blocks": [f"{label}: timed out after 30s"],
            "warnings": [],
        }

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        return {
            "blocks": [
                f"{label}: script error (exit {result.returncode}):\n"
                f"  {detail[:500]}\n\n"
                f"  Your rules file must exit 0 and print valid JSON.\n"
                f"  File: {path}"
            ],
            "warnings": [],
        }

    stdout = result.stdout.strip()
    if not stdout:
        return {"blocks": [], "warnings": []}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return {
            "blocks": [
                f"{label}: invalid JSON output: {e}\n\n"
                f"  Your rules file must print a JSON object like:\n"
                f'  {{"blocks": [...], "warnings": [...]}}\n\n'
                f"  Got: {stdout[:200]}\n"
                f"  File: {path}"
            ],
            "warnings": [],
        }

    blocks = data.get("blocks", [])
    warnings = data.get("warnings", [])

    if not isinstance(blocks, list) or not isinstance(warnings, list):
        return {
            "blocks": [
                f"{label}: 'blocks' and 'warnings' must be JSON arrays.\n"
                f"  File: {path}"
            ],
            "warnings": [],
        }

    # Tag messages with scope for traceability
    tag = f"[{scope}]"
    blocks = [f"{tag} {msg}" for msg in blocks]
    warnings = [f"{tag} {msg}" for msg in warnings]

    return {"blocks": blocks, "warnings": warnings}


def run_all_rules(widget_path: str, language: str) -> dict:
    """Find and run all rules files for the language. Returns merged results."""
    files = _rules_file_paths(language)
    if not files:
        return {"blocks": [], "warnings": [], "rules_run": 0}

    all_blocks = []
    all_warnings = []

    for entry in files:
        log.debug("Running %s rules: %s", entry["scope"], entry["path"])
        result = _run_rules_file(entry["path"], widget_path, language)
        all_blocks.extend(result["blocks"])
        all_warnings.extend(result["warnings"])

    return {
        "blocks": all_blocks,
        "warnings": all_warnings,
        "rules_run": len(files),
    }


# ---------------------------------------------------------------------------
# Templates - used by `cartograph rules init`
# ---------------------------------------------------------------------------

_TEMPLATE_PYTHON = """\
\"\"\"
Custom validation rules for Python widgets.

HOW THIS WORKS
--------------
This file runs automatically during `cartograph validate` (and therefore
`cartograph checkin`). Cartograph calls it with the widget directory as
the first argument. Your job is to inspect the widget and report problems.

Print a JSON object to stdout with two keys:

    {"blocks": [...], "warnings": [...]}

  blocks    - hard failures. Checkin is rejected, no override possible.
              Use for things that must never ship (banned patterns, etc).
  warnings  - soft issues. Checkin pauses, but the user can override with
              --override-warnings --override-reason "why it's ok".
              Use for things that are usually wrong but sometimes intentional.

Empty arrays (or no output at all) means all checks passed.

WHAT YOU HAVE ACCESS TO
-----------------------
The widget_path argument points to a standard widget directory:

    widget_path/
      widget.json       metadata (id, name, domain, version, dependencies)
      src/              source code - this is what gets imported
      tests/            test files
      examples/         example usage files

You can read any of these with normal file operations. For example:

    - os.walk(os.path.join(widget_path, "src"))     scan source files
    - os.walk(os.path.join(widget_path, "tests"))   scan test files
    - json.load(open(os.path.join(widget_path, "widget.json")))
                                                     read widget metadata

This is just a Python script. Use any stdlib module you want - ast for
parsing, re for patterns, pathlib if you prefer it. No special APIs needed.

RUNNING EXTRA TESTS
-------------------
Cartograph runs your widget's tests with its own flags (80% coverage, etc).
If you want more from your test engine (extra pytest flags, markers, plugins),
call it again from here via subprocess. Tests will run twice - once
Cartograph's way (the quality guarantee), once yours (your preferences).

    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "--timeout=120", "-x"],
        capture_output=True, text=True, cwd=widget_path,
    )
    if result.returncode != 0:
        blocks.append(f"Custom test run failed:\\n{result.stdout[-500:]}")
\"\"\"
import json
import os
import sys


def validate(widget_path):
    blocks = []
    warnings = []

    src_dir = os.path.join(widget_path, "src")
    test_dir = os.path.join(widget_path, "tests")
    examples_dir = os.path.join(widget_path, "examples")

    # --- Your checks go here ---
    #
    # The pattern is simple: check a condition, append a message.
    #
    #   if something_is_wrong:
    #       blocks.append("what's wrong and where")    # hard fail
    #
    #   if something_is_suspicious:
    #       warnings.append("what looks off")          # soft, overridable
    #
    # Examples (uncomment to use):

    # Block: ban specific imports in source code
    # BANNED = {"pickle", "subprocess", "eval"}
    # for root, _, files in os.walk(src_dir):
    #     for fname in files:
    #         if not fname.endswith(".py"): continue
    #         content = open(os.path.join(root, fname)).read()
    #         for banned in BANNED:
    #             if f"import {banned}" in content:
    #                 blocks.append(f"{fname} uses banned import: {banned}")

    # Warning: source files over 200 lines
    # for root, _, files in os.walk(src_dir):
    #     for fname in files:
    #         if not fname.endswith(".py"): continue
    #         count = sum(1 for _ in open(os.path.join(root, fname)))
    #         if count > 200:
    #             warnings.append(f"{fname} is {count} lines (max 200)")

    # Warning: fewer than 2 test files
    # tests = [f for f in os.listdir(test_dir) if f.startswith("test_")]
    # if len(tests) < 2:
    #     warnings.append(f"Only {len(tests)} test file(s) - consider more coverage")

    return {"blocks": blocks, "warnings": warnings}


if __name__ == "__main__":
    print(json.dumps(validate(sys.argv[1])))
"""

_TEMPLATE_JAVASCRIPT = """\
/**
 * Custom validation rules for JavaScript/TypeScript widgets.
 *
 * HOW THIS WORKS
 * --------------
 * This file runs automatically during `cartograph validate` (and therefore
 * `cartograph checkin`). Cartograph calls it with the widget directory as
 * a command-line argument. Your job is to inspect the widget and report problems.
 *
 * Print a JSON object to stdout with two keys:
 *
 *     {"blocks": [...], "warnings": [...]}
 *
 *   blocks    - hard failures. Checkin is rejected, no override possible.
 *   warnings  - soft issues. User can override with --override-warnings.
 *
 * Empty arrays (or no output at all) means all checks passed.
 *
 * WHAT YOU HAVE ACCESS TO
 * -----------------------
 * The widgetPath argument points to a standard widget directory:
 *
 *     widgetPath/
 *       widget.json       metadata (id, name, domain, version, dependencies)
 *       src/              source code
 *       tests/            test files
 *       examples/         example usage files
 *
 * Use normal fs operations to read any of these. This is just a Node script -
 * use any built-in module you want (fs, path, etc). No special APIs needed.
 *
 * RUNNING EXTRA TESTS
 * -------------------
 * Cartograph runs your widget's tests with its own flags. If you want more
 * from your test runner (extra jest flags, coverage config, etc), call it
 * again from here via child_process. Tests will run twice - once Cartograph's
 * way (the quality guarantee), once yours (your preferences).
 *
 *     const { execSync } = require("child_process");
 *     try {
 *         execSync("npx jest --coverage --coverageThreshold='{}'", { cwd: widgetPath });
 *     } catch (e) {
 *         blocks.push("Custom test run failed: " + e.stderr);
 *     }
 */
const fs = require("fs");
const path = require("path");

function validate(widgetPath) {
    const blocks = [];
    const warnings = [];

    const srcDir = path.join(widgetPath, "src");
    const testDir = path.join(widgetPath, "tests");
    const examplesDir = path.join(widgetPath, "examples");

    // --- Your checks go here ---
    //
    // The pattern is simple: check a condition, push a message.
    //
    //   if (somethingIsWrong) {
    //       blocks.push("what's wrong and where");    // hard fail
    //   }
    //   if (somethingIsSuspicious) {
    //       warnings.push("what looks off");          // soft, overridable
    //   }
    //
    // Examples (uncomment to use):

    // Block: ban specific patterns in source code
    // const BANNED = ["eval(", "document.write("];
    // if (fs.existsSync(srcDir)) {
    //     for (const fname of fs.readdirSync(srcDir)) {
    //         if (!fname.endsWith(".js") && !fname.endsWith(".ts")) continue;
    //         const content = fs.readFileSync(path.join(srcDir, fname), "utf8");
    //         for (const banned of BANNED) {
    //             if (content.includes(banned)) {
    //                 blocks.push(`${fname} uses banned pattern: ${banned}`);
    //             }
    //         }
    //     }
    // }

    // Warning: source files over 200 lines
    // if (fs.existsSync(srcDir)) {
    //     for (const fname of fs.readdirSync(srcDir)) {
    //         if (!fname.endsWith(".js") && !fname.endsWith(".ts")) continue;
    //         const lines = fs.readFileSync(path.join(srcDir, fname), "utf8").split("\\n").length;
    //         if (lines > 200) {
    //             warnings.push(`${fname} is ${lines} lines (max 200)`);
    //         }
    //     }
    // }

    // Warning: fewer than 2 test files
    // if (fs.existsSync(testDir)) {
    //     const tests = fs.readdirSync(testDir).filter(f => f.startsWith("test"));
    //     if (tests.length < 2) {
    //         warnings.push(`Only ${tests.length} test file(s) - consider more coverage`);
    //     }
    // }

    return { blocks, warnings };
}

console.log(JSON.stringify(validate(process.argv[2])));
"""

_TEMPLATE_NIM = """\
## Custom validation rules for Nim widgets.
##
## HOW THIS WORKS
## --------------
## This file runs automatically during `cartograph validate` (and therefore
## `cartograph checkin`). Cartograph calls it with the widget directory as
## the first argument. Your job is to inspect the widget and report problems.
##
## Print a JSON object to stdout with two keys:
##
##     {"blocks": [...], "warnings": [...]}
##
##   blocks    - hard failures. Checkin is rejected, no override possible.
##   warnings  - soft issues. User can override with --override-warnings.
##
## Empty arrays (or no output at all) means all checks passed.
##
## WHAT YOU HAVE ACCESS TO
## -----------------------
## The widgetPath argument points to a standard widget directory:
##
##     widgetPath/
##       widget.json       metadata (id, name, domain, version, dependencies)
##       src/              source code
##       tests/            test files
##       examples/         example usage files
##
## Use standard library modules (os, json, strutils) to inspect files.
## This is just a Nim script - no special APIs needed.
##
## RUNNING EXTRA TESTS
## -------------------
## Cartograph runs your widget's tests via nimble test. If you want to use
## testament (--megatest, custom patterns, etc), call it from here via
## execCmdEx. Tests will run twice - once Cartograph's way (the quality
## guarantee), once yours (your preferences).
##
##   let res = execCmdEx("testament --megatest pattern tests/")
##   if res.exitCode != 0:
##     blocks.add(%*("Custom test run failed: " & res.output))

import std/[json, os, strutils]

proc validate(widgetPath: string): JsonNode =
  var blocks = newJArray()
  var warnings = newJArray()

  let srcDir = widgetPath / "src"
  let testDir = widgetPath / "tests"
  let examplesDir = widgetPath / "examples"

  # --- Your checks go here ---
  #
  # The pattern is simple: check a condition, add a message.
  #
  #   if somethingIsWrong:
  #     blocks.add(%*"what's wrong and where")     # hard fail
  #
  #   if somethingIsSuspicious:
  #     warnings.add(%*"what looks off")           # soft, overridable
  #
  # Examples (uncomment to use):

  # Block: ban specific imports in source code
  # if dirExists(srcDir):
  #   for fpath in walkDirRec(srcDir):
  #     if not fpath.endsWith(".nim"): continue
  #     let content = readFile(fpath)
  #     for banned in ["os.execShellCmd", "system("]:
  #       if banned in content:
  #         blocks.add(%*(extractFilename(fpath) & " uses banned: " & banned))

  # Warning: source files over 200 lines
  # if dirExists(srcDir):
  #   for fpath in walkDirRec(srcDir):
  #     if not fpath.endsWith(".nim"): continue
  #     let count = readFile(fpath).splitLines().len
  #     if count > 200:
  #       warnings.add(%*(extractFilename(fpath) & " is " & $count & " lines (max 200)"))

  # Warning: fewer than 2 test files
  # if dirExists(testDir):
  #   var testCount = 0
  #   for fpath in walkDir(testDir):
  #     if fpath.path.endsWith(".nim"): inc testCount
  #   if testCount < 2:
  #     warnings.add(%*("Only " & $testCount & " test file(s) - consider more coverage"))

  result = %*{"blocks": blocks, "warnings": warnings}

echo $validate(paramStr(1))
"""

_TEMPLATE_PHP = """\
<?php
/**
 * Custom validation rules for PHP widgets.
 *
 * HOW THIS WORKS
 * --------------
 * This file runs automatically during `cartograph validate` (and therefore
 * `cartograph checkin`). Cartograph calls it with the widget directory as
 * the first argument. Your job is to inspect the widget and report problems.
 *
 * Print a JSON object to stdout with two keys:
 *
 *     {"blocks": [...], "warnings": [...]}
 *
 *   blocks    - hard failures. Checkin is rejected, no override possible.
 *               Use for things that must never ship (banned patterns, etc).
 *   warnings  - soft issues. Checkin pauses, but the user can override with
 *               --override-warnings --override-reason "why it's ok".
 *               Use for things that are usually wrong but sometimes intentional.
 *
 * Empty arrays (or no output at all) means all checks passed.
 *
 * WHAT YOU HAVE ACCESS TO
 * -----------------------
 * The $widgetPath argument points to a standard widget directory:
 *
 *     widgetPath/
 *       widget.json       metadata (id, name, domain, version, dependencies)
 *       src/              source code
 *       tests/            test files
 *       examples/         example usage files
 *
 * Use standard PHP functions (file_get_contents, glob, json_decode) to
 * inspect files. This is just a PHP script - no special APIs needed.
 *
 * RUNNING EXTRA TESTS
 * -------------------
 * Cartograph runs your widget's tests via vendor/bin/phpunit. If you want
 * to run additional PHPUnit suites or enforce custom test patterns, call
 * phpunit from here:
 *
 *   $res = shell_exec("php vendor/bin/phpunit --testsuite custom 2>&1");
 *   if ($res === null || str_contains($res, 'FAILURES')) {
 *       $blocks[] = "Custom test suite failed";
 *   }
 */

$widgetPath = $argv[1] ?? '.';
$blocks = [];
$warnings = [];

$srcDir      = $widgetPath . '/src';
$testDir     = $widgetPath . '/tests';
$examplesDir = $widgetPath . '/examples';

// --- Your checks go here ---
//
// The pattern is simple: check a condition, add a message.
//
//   if (somethingIsWrong) {
//       $blocks[] = "what's wrong and where";     // hard fail
//   }
//
//   if (somethingIsSuspicious) {
//       $warnings[] = "what looks off";           // soft, overridable
//   }
//
// Examples (uncomment to use):

// Block: ban specific function calls in source code
// $phpFiles = glob($srcDir . '/*.php') ?: [];
// foreach ($phpFiles as $file) {
//     $content = file_get_contents($file);
//     foreach (['exec(', 'shell_exec(', 'system('] as $banned) {
//         if (str_contains($content, $banned)) {
//             $blocks[] = basename($file) . " uses banned function: $banned";
//         }
//     }
// }

// Warning: source files over 200 lines
// $phpFiles = glob($srcDir . '/*.php') ?: [];
// foreach ($phpFiles as $file) {
//     $count = count(file($file));
//     if ($count > 200) {
//         $warnings[] = basename($file) . " is $count lines (max 200)";
//     }
// }

// Warning: fewer than 2 test files
// $testFiles = glob($testDir . '/*Test.php') ?: [];
// if (count($testFiles) < 2) {
//     $warnings[] = "Only " . count($testFiles) . " test file(s) - consider more coverage";
// }

echo json_encode(['blocks' => $blocks, 'warnings' => $warnings]);
"""

_TEMPLATES = {
    "python": _TEMPLATE_PYTHON,
    "javascript": _TEMPLATE_JAVASCRIPT,
    "typescript": _TEMPLATE_JAVASCRIPT,
    "angular": _TEMPLATE_JAVASCRIPT,
    "nim": _TEMPLATE_NIM,
    "php": _TEMPLATE_PHP,
}


def get_template(language: str) -> str | None:
    """Return a rules file template for the language, or None if unsupported."""
    return _TEMPLATES.get(language)


def get_rules_filename(language: str) -> str | None:
    """Return the rules filename for this language."""
    info = _LANGUAGE_RULES.get(language)
    return info[0] if info else None
