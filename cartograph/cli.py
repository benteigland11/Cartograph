"""
Cartograph CLI — manage your widget library from the terminal.

Every command that takes a path defaults to the current directory (.).
Output is always JSON so both humans and AI agents can consume it.
"""

import argparse
import json
import os
import sys


def _out(result: dict) -> None:
    print(json.dumps(result, indent=2))


def _err(result: dict) -> None:
    _out(result)
    sys.exit(1)


def _resolve(path: str) -> str:
    return os.path.abspath(path)


def _carto():
    from .engine import Cartograph, LIBRARY_PATH
    return Cartograph(LIBRARY_PATH)


def _preflight_language(language: str) -> None:
    """Exit with a clear message if the language engine's system deps aren't met."""
    from .languages import get_engine
    engine = get_engine(language)
    if engine is None:
        return
    ok, msg = engine.check_available()
    if not ok:
        print(f"\n  ✗ {msg}\n", file=sys.stderr)
        sys.exit(1)


def _preflight_from_path(path: str) -> None:
    """Read widget.json language and run preflight check."""
    try:
        with open(os.path.join(path, "widget.json")) as f:
            language = json.load(f).get("tech_stack", {}).get("language", "python")
        _preflight_language(language)
    except Exception:
        pass  # let the command itself report the missing file


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_search(args):
    local = _carto().search(
        query=args.query,
        domain_filter=args.domain,
        language_filter=args.language,
        top_k=args.top_k,
    )

    from .auth import is_authenticated
    if not is_authenticated():
        _out(local)
        return

    from .cloud import search as cloud_search
    cloud = cloud_search(
        query=args.query,
        domain_filter=args.domain,
        language_filter=args.language,
        top_k=args.top_k,
    )

    # Merge: local results first, then cloud widgets not already present locally
    local_ids = {w["id"] for w in local.get("widgets", [])}
    extra = [w for w in cloud.get("widgets", []) if w["id"] not in local_ids]

    merged = {
        "widgets": local.get("widgets", []) + extra,
        "local_count": len(local.get("widgets", [])),
        "cloud_count": len(extra),
    }
    if cloud.get("error"):
        merged["cloud_error"] = cloud["error"]
    _out(merged)


def cmd_inspect(args):
    result = _carto().inspect(
        widget_id=args.widget_id,
        show_source=args.source,
        show_all_versions=args.all_versions,
        show_reviews=args.reviews,
        version=getattr(args, "version", None),
    )
    _out(result)


def cmd_install(args):
    result = _carto().install(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_uninstall(args):
    result = _carto().uninstall(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_update(args):
    result = _carto().update(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_delete(args):
    result = _carto().delete(
        widget_id=args.widget_id,
        confirm=args.confirm,
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_create(args):
    _preflight_language(args.language)
    result = _carto().create(
        item_id=args.widget_id,
        language=args.language,
        domain=args.domain,
        name=args.name,
        target_dir=_resolve(args.target),
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_validate(args):
    _preflight_from_path(_resolve(args.path))
    result = _carto().validate_item(path=_resolve(args.path))
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_checkin(args):
    _preflight_from_path(_resolve(args.path))
    result = _carto().checkin(
        path=_resolve(args.path),
        reason=args.reason,
        version_bump=args.bump,
        override_warnings=args.override_warnings,
        override_reason=args.override_reason or "",
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_status(args):
    target = _resolve(args.target)

    if args.widget_id:
        result = _carto().widget_status(widget_id=args.widget_id, target_dir=target)
        if result.get("error"):
            _err(result)
        _out(result)
        return

    # No widget_id — scan all installed widgets
    install_dir = os.path.join(target, "cartograph")
    if not os.path.isdir(install_dir):
        _err({"error": f"No cartograph/ directory found at {target}"})

    widget_ids = [
        d for d in os.listdir(install_dir)
        if os.path.isfile(os.path.join(install_dir, d, "widget.json"))
    ]

    if not widget_ids:
        _out({"installed": 0, "widgets": []})
        return

    carto = _carto()
    widgets = []
    for wid in sorted(widget_ids):
        r = carto.widget_status(widget_id=wid, target_dir=target)
        widgets.append(r)

    _out({
        "installed": len(widgets),
        "outdated": sum(1 for w in widgets if w.get("outdated")),
        "modified": sum(1 for w in widgets if w.get("modified")),
        "widgets": widgets,
    })


def cmd_login(args):
    from .cloud import login_with_token
    token = args.token
    if not token:
        # Prompt when running interactively; CI should use --token or CARTOGRAPH_TOKEN
        if sys.stdin.isatty():
            import getpass
            token = getpass.getpass("  Cartograph token: ").strip()
        else:
            _err({"error": "Provide a token with --token or set CARTOGRAPH_TOKEN"})
    result = login_with_token(token)
    if "error" in result:
        _err(result)
    _out(result)


def cmd_logout(args):
    from .auth import clear_token, is_authenticated
    if not is_authenticated():
        _out({"status": "already_logged_out"})
        return
    clear_token()
    _out({"status": "success", "message": "Logged out."})


def cmd_push(args):
    from .auth import is_authenticated
    if not is_authenticated():
        _err({"error": "Not authenticated. Run: cartograph login"})

    path = _resolve(args.path)
    _preflight_from_path(path)

    # widget_id comes from widget.json if not given explicitly
    widget_id = args.widget_id
    if not widget_id:
        try:
            with open(os.path.join(path, "widget.json")) as f:
                widget_id = json.load(f).get("id")
        except Exception:
            pass
    if not widget_id:
        _err({"error": "Could not determine widget_id. Pass it explicitly or run from the widget directory."})

    from .cloud import push
    result = push(path, widget_id, visibility=args.visibility)
    if "error" in result:
        _err(result)
    _out(result)


def cmd_rate(args):
    result = _carto().add_review(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
        score=args.score,
        comment=args.comment,
    )
    if result.get("error"):
        _err(result)
    _out(result)


def cmd_doctor(args):
    import shutil
    import subprocess

    groups = []  # list of (group_name, [(label, ok, detail, fix), ...])

    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except Exception as e:
            return False, str(e)

    # --- Library (auto-setup if missing) ---
    from .engine import LIBRARY_PATH, _ensure_library
    lib_checks = []
    if not os.path.isdir(LIBRARY_PATH):
        try:
            _ensure_library(LIBRARY_PATH)
            lib_checks.append(("Library", True, f"Created at {LIBRARY_PATH}", None))
        except Exception as e:
            lib_checks.append(("Library", False, str(e), "Check disk permissions"))
    else:
        lib_checks.append(("Library", True, LIBRARY_PATH, None))
    groups.append(("Library", lib_checks))

    # --- Python ---
    import sys
    py_checks = []
    py_checks.append(("Python", True, sys.executable, None))

    ok, out = run([sys.executable, "-m", "pytest", "--version"])
    py_checks.append(("pytest", ok,
                       out.splitlines()[0] if ok else "not found",
                       "pip install pytest" if not ok else None))

    ok, out = run([sys.executable, "-m", "coverage", "--version"])
    py_checks.append(("coverage", ok,
                       out.splitlines()[0] if ok else "not found",
                       "pip install coverage" if not ok else None))
    groups.append(("Python", py_checks))

    # --- JavaScript ---
    js_checks = []
    node = shutil.which("node")
    if node:
        ok, out = run(["node", "--version"])
        version_str = out.strip()
        try:
            major = int(version_str.lstrip("v").split(".")[0])
            version_ok = major >= 18
        except ValueError:
            version_ok = False
        js_checks.append(("Node.js", version_ok,
                           version_str if version_ok else f"{version_str} (need ≥18)",
                           "Install Node.js 18+ — nodejs.org" if not version_ok else None))
    else:
        js_checks.append(("Node.js", False, "not found", "Install Node.js 18+ — nodejs.org"))

    npx = shutil.which("npx") or shutil.which("npx.cmd")
    js_checks.append(("npx", npx is not None,
                       "found" if npx else "not found",
                       "Reinstall Node.js — npx ships with it" if not npx else None))

    if npx:
        ok, out = run(["npx", "--yes", "vitest", "--version"])
        js_checks.append(("vitest", ok,
                           out.splitlines()[0] if ok else "not found",
                           "npm install -g vitest" if not ok else None))

        ok, out = run(["npx", "--yes", "esbuild", "--version"])
        js_checks.append(("esbuild", ok,
                           out.strip() if ok else "not found",
                           "npm install -g esbuild" if not ok else None))
    groups.append(("JavaScript", js_checks))

    # --- Render ---
    all_checks = [c for _, checks in groups for c in checks]
    passed = sum(1 for c in all_checks if c[1])
    total = len(all_checks)
    all_ok = passed == total

    print()
    for group_name, checks in groups:
        print(f"  {group_name}")
        for label, ok, detail, fix in checks:
            mark = "✓" if ok else "✗"
            print(f"    [{mark}] {label:<12}  {detail}")
            if not ok and fix:
                print(f"          → {fix}")
        print()

    if all_ok:
        print(f"  No issues found.\n")
    else:
        issues = total - passed
        print(f"  {issues} issue{'s' if issues > 1 else ''} found.\n")
        sys.exit(1)


_CLAUDE_MD_CONSUMER = """\
## Cartograph

Cartograph is a shared widget library. Widgets are reusable, self-contained
code modules. They live in your project under cartograph/<widget_id>/.

### One rule: search before writing reusable code

Before implementing anything self-contained (a UI component, a parser, a retry
helper, a data pipeline, a formatter), run `cartograph search`. If something
useful exists, install and use it instead of writing from scratch.

### Install workflow
1. `cartograph search <query>` — use a single keyword or core concept (e.g. "retry", "debounce", "pagination"). No results? Go broader — try a synonym or the underlying concept, not a description.
2. `cartograph inspect <widget_id> --source --reviews` — read the code and feedback
3. `cartograph install <widget_id>` — installs to ./cartograph/<widget_id>/
4. Import from `cartograph/<widget_id>/src/` — check examples/ for usage patterns
5. `cartograph rate <widget_id> <score> --comment "..."` — rate after using

### Commands
`<arg>` = required  `[arg]` = optional  defaults shown where relevant

    cartograph search <query>
        [--domain backend|data|ml|security|infra|frontend|universal]
        [--language python|javascript]

    cartograph inspect <widget_id>
        [--source]         include source files
        [--reviews]        include review comments
        [--all-versions]   list full version history

    cartograph install <widget_id> [--target .] [--version X]
    cartograph uninstall <widget_id> [--target .]
    cartograph update <widget_id> [--target .] [--version X]
    cartograph status <widget_id> [--target .]
    cartograph rate <widget_id> <score 1-5> [--comment "..."] [--target .]
    cartograph doctor
"""

_CLAUDE_MD_DEVELOPER = """\
## Cartograph

Cartograph is a shared widget library. Widgets are reusable, self-contained
code modules. They live in your project under cartograph/<widget_id>/.

### Two rules to follow on every task

**1. Search before writing reusable code.**
Before implementing anything self-contained (a UI component, a parser, a retry
helper, a data pipeline, a formatter), run `cartograph search`. If something
useful exists, install and use it instead of writing from scratch.

**2. Spot generalizable work as you go and suggest it to the user.**
As you write code, watch for logic that has no project-specific assumptions —
a clean abstraction, a handy formatter, a robust error handler. When you notice
one, suggest packaging it: "This would work well as a widget — it'll be easier
to test, improve, and reuse across projects. Want me to package it?"
Let the user decide. If they say yes, do it before moving on while the context
is fresh.

### Install workflow
1. `cartograph search <query>` — use a single keyword or core concept (e.g. "retry", "debounce", "pagination"). No results? Go broader — try a synonym or the underlying concept, not a description.
2. `cartograph inspect <widget_id> --source --reviews` — read the code and feedback
3. `cartograph install <widget_id>` — installs to ./cartograph/<widget_id>/
4. Import from `cartograph/<widget_id>/src/` — check examples/ for usage patterns
5. `cartograph rate <widget_id> <score> --comment "..."` — rate after using

### Checkin workflow
You have finished writing a piece of logic. Before moving on, ask:
"Could this work in another project without modification?" If yes, package it.

1. `cartograph create <widget_id> --language python|javascript --domain <domain> [--target .]`
   Widget lands at ./cartograph/<widget_id>/
   widget_id format: <domain>-<name>-<language> e.g. logic-retry-backoff-python
2. Copy your code into src/. Clean it up:
   - Remove anything project-specific (paths, config, hardcoded values)
   - Declare all third-party deps in widget.json tech_stack.dependencies
3. Write tests in tests/ — 80%+ coverage required
4. Fill in examples/example_usage.* — must run and exit cleanly with no user input
   Optionally add examples/usage_hint.* for real app integration patterns (not validated)
5. `cartograph validate [.]` — fix every issue before proceeding
6. `cartograph checkin [.] --reason "..."` — one-line description of what and why
7. `cartograph rate <widget_id> <score> --comment "..."` — honest score, one specific comment

### Editing installed widgets
Do not edit files inside cartograph/<widget_id>/ directly — local edits are
overwritten on update. Wrap or extend in your own code instead.
Found a bug or improvement? Fix it and `cartograph checkin` to contribute it back.

### Commands
`<arg>` = required  `[arg]` = optional  defaults shown where relevant

    cartograph search <query>
        [--domain backend|data|ml|security|infra|frontend|universal]
        [--language python|javascript]

    cartograph inspect <widget_id>
        [--source]         include source files
        [--reviews]        include review comments
        [--all-versions]   list full version history

    cartograph install <widget_id> [--target .] [--version X]
    cartograph uninstall <widget_id> [--target .]
    cartograph update <widget_id> [--target .] [--version X]
    cartograph status <widget_id> [--target .]

    cartograph create <widget_id>
        --language python|javascript          REQUIRED
        --domain backend|data|ml|security|infra|frontend|universal  REQUIRED
        [--target .]

    cartograph validate [path]               path defaults to .
    cartograph checkin [path]                path defaults to .
        --reason "what changed and why"      REQUIRED
        [--bump patch|minor|major]           defaults to minor

    cartograph rate <widget_id> <score 1-5> [--comment "..."] [--target .]
    cartograph doctor
    cartograph setup [--mode consumer|developer|maintainer]
        [--write]          append to ./CLAUDE.md in current project
        [--write --global] append to ~/.claude/CLAUDE.md instead
"""

_CLAUDE_MD_MAINTAINER = """\
## Cartograph — Maintainer Mode

Your role is library steward. Your primary goal is the health and growth of
the widget library, not project feature work.

### What to do each session

**1. Audit existing widgets.**
`cartograph search` to browse, `cartograph inspect <id> --reviews` to read feedback.
- Low rating or negative reviews → fix the issue and checkin an improvement
- Broken examples → fix them
- Low test coverage → add tests

**2. Improve low-rated widgets.**
Read the reviews. Find the friction. Fix it, bump the version, write a clear
reason in `cartograph checkin [.] --reason "..."`.

**3. Create new widgets for recurring patterns.**
If a pattern keeps appearing across projects but isn't in the library, build it:
`cartograph create` → develop → `cartograph validate` → `cartograph checkin`.

Every change must pass `cartograph validate` and `cartograph checkin` before
it counts. Edits that stay local help nobody.

### Checkin workflow
1. `cartograph create <widget_id> --language X --domain X`
2. Copy + clean code into src/ — no project-specific assumptions
3. Write tests (80%+ coverage), fill in examples/example_usage.*
4. `cartograph validate [.]` — must pass cleanly
5. `cartograph checkin [.] --reason "..."` — clear changelog entry
6. `cartograph rate <widget_id> <score> --comment "..."`

### Commands
`<arg>` = required  `[arg]` = optional  defaults shown where relevant

    cartograph search <query>
        [--domain backend|data|ml|security|infra|frontend|universal]
        [--language python|javascript]

    cartograph inspect <widget_id>
        [--source]         include source files
        [--reviews]        include review comments
        [--all-versions]   list full version history

    cartograph install <widget_id> [--target .] [--version X]
    cartograph uninstall <widget_id> [--target .]
    cartograph update <widget_id> [--target .] [--version X]
    cartograph status <widget_id> [--target .]

    cartograph create <widget_id>
        --language python|javascript          REQUIRED
        --domain backend|data|ml|security|infra|frontend|universal  REQUIRED
        [--target .]

    cartograph validate [path]               path defaults to .
    cartograph checkin [path]                path defaults to .
        --reason "what changed and why"      REQUIRED
        [--bump patch|minor|major]           defaults to minor

    cartograph rate <widget_id> <score 1-5> [--comment "..."] [--target .]
    cartograph doctor
"""

_CLAUDE_MD_BY_MODE = {
    "consumer":   _CLAUDE_MD_CONSUMER,
    "developer":  _CLAUDE_MD_DEVELOPER,
    "maintainer": _CLAUDE_MD_MAINTAINER,
}

_AGENT_FILENAMES = {
    "claude":       "CLAUDE.md",
    "codex":        "AGENTS.md",
    "gemini":       "GEMINI.md",
    "antigravity":  "GEMINI.md",
    "cursor":       os.path.join(".cursor", "rules", "cartograph.mdc"),
}

_GLOBAL_DIRS = {
    "claude":      os.path.expanduser("~/.claude"),
    "codex":       os.path.expanduser("~/.codex"),
    "gemini":      os.path.expanduser("~/.gemini"),
    "antigravity": os.path.expanduser("~/.gemini"),
    # cursor: no global file — global rules live in the editor's Settings UI
}


def _prompt(question, options):
    """Simple numbered menu. Returns the chosen option string."""
    print(f"\n  {question}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}) {opt}")
    while True:
        raw = input("  > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print(f"  Enter a number 1-{len(options)} or one of: {', '.join(options)}")


def cmd_stats(args):
    from collections import defaultdict
    widgets = _carto().widgets

    if not widgets:
        print("\n  Library is empty.\n")
        return

    by_language = defaultdict(int)
    by_domain   = defaultdict(int)
    rated       = []
    installed   = []

    for w in widgets:
        lang = w.get("language", "unknown")
        if isinstance(lang, list):
            lang = lang[0] if lang else "unknown"
        by_language[lang] += 1
        by_domain[w.get("domain", "unknown")] += 1

        if w.get("rating", 0):
            rated.append((w["name"], w["rating"]))
        if w.get("install_count", 0):
            installed.append((w["name"], w["install_count"]))

    rated.sort(key=lambda x: x[1], reverse=True)
    installed.sort(key=lambda x: x[1], reverse=True)

    all_ratings = [w.get("rating", 0) for w in widgets if w.get("rating", 0)]
    avg_rating  = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0
    total_installs = sum(w.get("install_count", 0) for w in widgets)

    print()
    print(f"  Library  {len(widgets)} widgets  |  {total_installs} total installs  |  avg rating {avg_rating}/5.0")
    print()

    print("  By language")
    for lang, count in sorted(by_language.items()):
        print(f"    {lang:<16}  {count}")
    print()

    print("  By domain")
    for domain, count in sorted(by_domain.items()):
        print(f"    {domain:<16}  {count}")
    print()

    if installed:
        print("  Most installed")
        for name, count in installed[:5]:
            print(f"    {name:<32}  {count} installs")
        print()

    if rated:
        print("  Top rated")
        for name, rating in rated[:5]:
            print(f"    {name:<32}  {rating}/5.0")
        print()


def _cursor_mdc(content):
    """Wrap plain markdown content in Cursor's MDC frontmatter format."""
    return (
        "---\n"
        "description: Cartograph widget library usage rules\n"
        "alwaysApply: true\n"
        "---\n\n"
    ) + content


def cmd_setup(args):
    interactive = sys.stdin.isatty() and not any([args.agent, args.mode != "developer", args.write])

    if interactive:
        print("\n  Cartograph setup\n")
        agent = _prompt("Which AI agent?", ["claude", "codex", "gemini", "antigravity", "cursor"])
        mode  = _prompt("Usage mode?",     ["developer", "consumer", "maintainer"])
        if agent == "cursor":
            scope = "project (./)"; use_global = False; write = True
        else:
            scope = _prompt("Write to?", ["project (./)", "global (~/)"])
            write = True
            use_global = scope.startswith("global")
    else:
        agent      = args.agent or "claude"
        mode       = args.mode
        write      = args.write
        use_global = args.glob

    if use_global and agent == "cursor":
        print("\n  Cursor stores global rules in the editor UI (Settings > Rules > User Rules),")
        print("  not as a file on disk. Run without --global to write a project-level rules file.\n")
        sys.exit(1)

    content  = _CLAUDE_MD_BY_MODE[mode]
    filename = _AGENT_FILENAMES[agent]

    if agent == "cursor":
        content = _cursor_mdc(content)

    if write:
        if use_global:
            target_dir = _GLOBAL_DIRS[agent]
            os.makedirs(target_dir, exist_ok=True)
        else:
            target_dir = os.getcwd()
        filepath = os.path.join(target_dir, filename)
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

        marker = "## Cartograph"
        if os.path.exists(filepath):
            existing = open(filepath).read()
            if marker in existing:
                print(f"\n  Cartograph section already exists in {filepath}")
                print(f"  Remove the existing ## Cartograph section and re-run to replace it.\n")
                sys.exit(1)
        with open(filepath, "a") as f:
            f.write("\n" + content)
        print(f"\n  Written to {filepath}\n")
    else:
        print(content)
        print(f"  # Add this to your {filename}, or run: cartograph setup --write")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cartograph",
        description="Cartograph widget library manager",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # search
    p = sub.add_parser("search", help="Search the widget library")
    p.add_argument("query", help="Search query")
    p.add_argument("--domain", default=None, help="Filter by domain")
    p.add_argument("--language", default=None, help="Filter by language")
    p.add_argument("--top-k", type=int, default=10, dest="top_k")
    p.set_defaults(func=cmd_search)

    # inspect
    p = sub.add_parser("inspect", help="Show widget details")
    p.add_argument("widget_id")
    p.add_argument("--source", action="store_true", help="Include source files")
    p.add_argument("--all-versions", action="store_true", dest="all_versions")
    p.add_argument("--reviews", action="store_true")
    p.add_argument("--version", default=None, help="Inspect a specific historical version (e.g. 1.2.0)")
    p.set_defaults(func=cmd_inspect)

    # install
    p = sub.add_parser("install", help="Install a widget into your project")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_install)

    # uninstall
    p = sub.add_parser("uninstall", help="Remove a widget from your project")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_uninstall)

    # update
    p = sub.add_parser("update", help="Update an installed widget to the latest version")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_update)

    # delete
    p = sub.add_parser("delete", help="Show widget stats (safe) or permanently remove with --confirm")
    p.add_argument("widget_id")
    p.add_argument("--confirm", action="store_true",
                   help="Actually delete the widget from the library (irreversible)")
    p.set_defaults(func=cmd_delete)

    # create
    p = sub.add_parser("create", help="Scaffold a new widget")
    p.add_argument("widget_id")
    p.add_argument("--language", required=True, choices=["python", "javascript"])
    p.add_argument("--domain", required=True,
                   choices=["backend", "data", "ml", "security", "infra", "frontend", "universal"])
    p.add_argument("--name", default=None, help="Human-readable display name")
    p.add_argument("--target", default=".", help="Where to create the widget (default: .)")
    p.set_defaults(func=cmd_create)

    # validate
    p = sub.add_parser("validate", help="Run the validation pipeline on a widget")
    p.add_argument("path", nargs="?", default=".", help="Widget directory (default: .)")
    p.set_defaults(func=cmd_validate)

    # checkin
    p = sub.add_parser("checkin", help="Check a widget into the library")
    p.add_argument("path", nargs="?", default=".", help="Widget directory (default: .)")
    p.add_argument("--reason", required=True, help="What changed and why")
    p.add_argument("--bump", default="minor", choices=["major", "minor", "patch"],
                   help="Version bump type (default: minor)")
    p.add_argument("--override-warnings", action="store_true", dest="override_warnings")
    p.add_argument("--override-reason", default=None, dest="override_reason")
    p.set_defaults(func=cmd_checkin)

    # status
    p = sub.add_parser("status", help="Check installed widget(s) — omit widget_id to scan all")
    p.add_argument("widget_id", nargs="?", default=None)
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_status)

    # rate
    p = sub.add_parser("rate", help="Rate an installed widget")
    p.add_argument("widget_id")
    p.add_argument("score", type=float, help="Score from 1.0 to 5.0")
    p.add_argument("--comment", default=None)
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_rate)

    # setup
    p = sub.add_parser("setup", help="Generate and optionally write agent instructions (interactive in terminal)")
    p.add_argument("--agent", default=None,
                   choices=["claude", "codex", "gemini", "antigravity", "cursor"],
                   help="Target agent: claude=CLAUDE.md, codex=AGENTS.md, gemini/antigravity=GEMINI.md, cursor=.cursor/rules/cartograph.mdc")
    p.add_argument("--mode", default="developer", choices=["consumer", "developer", "maintainer"],
                   help="Usage mode (default: developer)")
    p.add_argument("--write", action="store_true",
                   help="Write to the target file instead of printing")
    p.add_argument("--global", action="store_true", dest="glob",
                   help="With --write: write to global config dir instead of current project")
    p.set_defaults(func=cmd_setup)

    # login
    p = sub.add_parser("login", help="Authenticate with the Cartograph cloud registry")
    p.add_argument("--token", default=None,
                   help="API token (prompted interactively if omitted in a terminal)")
    p.set_defaults(func=cmd_login)

    # logout
    p = sub.add_parser("logout", help="Remove stored Cartograph cloud credentials")
    p.set_defaults(func=cmd_logout)

    # push
    p = sub.add_parser("push", help="Publish a validated widget to the cloud registry")
    p.add_argument("widget_id", nargs="?", default=None,
                   help="Widget ID to push (inferred from widget.json if omitted)")
    p.add_argument("path", nargs="?", default=".",
                   help="Widget directory (default: .)")
    p.add_argument("--visibility", default="public", choices=["public", "private"],
                   help="Registry visibility (default: public)")
    p.set_defaults(func=cmd_push)

    # stats
    p = sub.add_parser("stats", help="Show library statistics")
    p.set_defaults(func=cmd_stats)

    # doctor
    p = sub.add_parser("doctor", help="Check that all language engine dependencies are installed")
    p.set_defaults(func=cmd_doctor)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
