# Cartograph

[![Tests](https://github.com/benteigland11/Cartograph/actions/workflows/test.yml/badge.svg)](https://github.com/benteigland11/Cartograph/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/cartograph-cli?cacheSeconds=60)](https://pypi.org/project/cartograph-cli/)

A local first reusable code registry for AI agents. Search, install, create, validate, and check in code modules across projects. Only requires Python. Other languages in the repo are native validation scanners for their respective widget types. The tool is designed to use the languages you have installed.

### Demonstration of creating, installing, and composing widgets

<a href="https://youtu.be/wN0v84O3wxg">
  <img src="https://img.youtube.com/vi/wN0v84O3wxg/hqdefault.jpg" width="620" alt="Cartograph Demo">
</a>

## Why Cartograph

AI agents write a lot of code, but it disappears. Each new project starts from scratch, and agents can't naturally reuse logic across codebases without somewhere to put it.

Cartograph came out of a personal frustration. Features that took 10 to 20 hours to polish with AI coding tools would need to be rebuilt almost from scratch when the next project needed them and most of the hardened logic would be gone. Then I built a basic engine, and those same features could be dropped into a new project in minutes.

Those same widgets have now been reused across many projects and have settled into a quiet loop of continuous improvement. Each time a new edge case surfaces, the fix goes back into the library, and every project that installs it going forward starts with that bug already squashed.

*Per aspera ad astra.* Through hardships to the stars. This is a tool that takes struggle to get the benefits, and they will compound.

## What is a widget?

A widget is a reusable code module with tests, examples, metadata, and declared dependencies. Each widget is self-contained and language-specific.

```
cg/backend_retry_backoff_python/
  widget.json          # metadata, version, dependencies
  src/                 # source code
  tests/               # test files (80%+ coverage required)
  examples/
    example_usage.py   # must run successfully
```

Widget IDs follow `<domain>-<name>-<language>`, for example `backend-retry-backoff-python` or `algorithms-edit-distance-nim`.

When installed into a project, widgets live under `cg/` in your working directory.

## Quick start

```bash
pip install cartograph-cli
```

Set up instructions for your AI agent:

```bash
cartograph setup
```

This auto-detects your agent (Claude, Cursor, Codex, Gemini) and appends Cartograph instructions to the appropriate config file. Use `--print` to preview without writing.

### Codex

For Codex, you can either let Cartograph write the agent instructions:

```bash
cartograph setup --agent codex
```

Or register Cartograph directly as an MCP server:

```bash
codex mcp add cartograph -- cartograph
```

## Example workflow

```bash
# Create a new widget
cartograph create backend-retry-backoff-python --language python --domain backend

# Write your code in cg/backend_retry_backoff_python/src/ and tests/

# Validate it (runs tests, coverage, contamination scanning)
cartograph validate cg/backend_retry_backoff_python

# Check it into your library
cartograph checkin cg/backend_retry_backoff_python --reason "initial implementation"

# Later, in a different project:
cartograph search "retry backoff"
cartograph install backend-retry-backoff-python
```

## Philosophy

This CLI tool is built with agents in mind first. Commands are non-interactive and output JSON so both humans and AI agents can consume them.

We only ship what we can validate. Every widget that enters the library has passed a full pipeline: structure checks, manifest validation, coverage enforcement, contamination scanning, example execution, and versioning. If the pipeline can't run it, it doesn't go in.

Supporting a language means owning its full validation pipeline, not just generating files. We add languages as those pipelines are ready, not before.

## Common commands

The commands you'll reach for daily. All run from your project root.

```
cartograph search <query>                              # find a widget
cartograph install <widget_id>                         # install into cg/
cartograph create <name> --domain <d> --language <l>   # scaffold a new widget
cartograph validate [path]                             # run the full pipeline
cartograph checkin [path] --reason "..."               # push edits back
cartograph status                                      # installed widgets
cartograph setup                                       # configure your agent
```

**Full reference:** `cartograph <command> --help` for a single command, or
`cartograph setup --print` for the complete surface grouped by section.
The reference is generated directly from the CLI, so it never drifts from
what the tool actually supports.

## Language support

- **Python**: pytest, coverage.py, AST-based contamination scanner
- **JavaScript/TypeScript**: vitest, native JS scanner, React component support
- **Nim**: nimble, std/unittest, native Nim scanner, stdlib-aware import checking
- **OpenSCAD**: renders to STL, non-empty mesh check, Python contamination scanner (OpenSCAD has no file I/O). Requires 2021.01+ for `assert()` support. BOSL2 optional.
- **SystemVerilog**: Icarus Verilog (iverilog + vvp), `-g2012` mode. Enforces `always_comb`/`always_ff` (legacy `always @(...)` blocked). Contamination scanner checks vendor primitives, simulation-only constructs (`initial`, `#delay`, `$display`), blocking/non-blocking assignment misuse, and hardcoded constants. Vendor primitives allowed when the vendor library is declared as a dependency.
- **Angular**: Angular CLI (`ng test` + `ng build`), Karma + Jasmine with ChromeHeadless, 80% coverage via `karma.conf.js` thresholds. Standalone components (Angular 14+). Reuses JS contamination scanner. Example validation: `ng build` (build artifact, not script execution). Requires `@angular/cli` globally and Chrome/Chromium installed.
- **PHP**: Composer + PHPUnit 11, Xdebug or PCOV for coverage, 80% threshold via `--min-coverage`. PSR-4 autoloading under `Cartograph\` namespace. Contamination scanner blocks WordPress globals (`wp_*`, `add_action`, `$wpdb`, etc.) and `echo` in src/ to enforce pure PHP utility widgets.

Each language has its own validation engine. The contamination scanners are written in the target language itself where possible (Python uses AST, JS uses a token-based parser, Nim uses a line-based scanner). OpenSCAD and SystemVerilog use Python-based scanners since neither language has general-purpose file I/O suitable for static analysis tooling.

## Cloud registry

The CLI is built around a local registry on your machine. It also supports an optional cloud registry for sharing widgets across teams or publicly.

The hosted registry is in early development. The local engine is more ready and does not depend on cloud availability. If the registry is down or unreachable, everything local continues to work.

To point at your own registry instance:

```bash
export CARTOGRAPH_REGISTRY_URL=https://your-registry.example.com
```

`cartograph login` opens a browser-based authentication flow provided by whichever registry you're connected to.

## Development

```bash
pip install -e .
git config core.hooksPath .githooks   # enable the pre-push hook
pytest
```

The widget library lives in your platform's user data directory. To override the location, set `WIDGET_LIBRARY_PATH`. When running from source, a `Widget_Library/` directory alongside this repo takes precedence so local edits work without configuration.

Run `cartograph doctor` to check that all language engine dependencies (pytest, coverage, node, npx, vitest, nim, nimble, openscad, iverilog) are installed correctly.

### Pre-push checks and release preflight

The tracked `.githooks/pre-push` hook runs two fast checks in ~20-30 seconds before every push:

1. Import smoke (catches syntax errors).
2. Wheel-install smoke (build into a tempdir venv, verify `cartograph setup --print` still works — catches the dogfood-path-resolution class of bug that v0.5.29 shipped).

For a release push, run the full gauntlet first (~5-6 minutes, includes pytest):

```bash
./scripts/preflight.sh && git push origin master
# then tag:
git tag vX.Y.Z && git push origin vX.Y.Z
```
