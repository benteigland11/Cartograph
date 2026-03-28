# Cartograph

A shared widget library for AI agents. Search, install, create, validate, and check in reusable code across projects.

## Why Cartograph

AI agents write a lot of code, but it disappears. Each new project starts from scratch, and agents can't naturally reuse logic across codebases without somewhere to put it.

Cartograph came out of a personal frustration. Features that took 10 to 20 hours to polish with AI coding tools would need to be rebuilt almost from scratch when the next project needed them. Once a shared library existed, those same features could be dropped into a new project in minutes.

Those same widgets have now been reused across many projects and have settled into a quiet loop of continuous improvement. Each time a new edge case surfaces, the fix goes back into the library, and every project that installs it going forward starts with that bug already squashed.

## Philosophy

We only ship what we can validate. Every widget that enters the library has passed a full pipeline: structure checks, manifest validation, coverage enforcement, contamination scanning, example execution, and versioning. If the pipeline can't run it, it doesn't go in.

Supporting a language means owning its full validation pipeline, not just generating files. We'll add languages as those pipelines are ready, not before.

## Quick Start

```bash
pip install cartograph-cli
```

Then generate instructions for your AI agent:

```bash
cartograph setup
```

Running in a terminal, `cartograph setup` walks you through choosing your agent (Claude, Codex, Gemini, Antigravity, Cursor) and writes the instruction block to the right config file so your agent knows how to use the library.

To do it non-interactively:

```bash
cartograph setup --agent claude --write
```

## Commands

```
cartograph search <query>
    [--domain backend|data|ml|security|infra|frontend|universal]
    [--language python|javascript|nim]

cartograph inspect <widget_id>
    [--source]           include source files
    [--reviews]          include review comments
    [--all-versions]     list full version history
    [--version X]        inspect a specific historical version

cartograph install <widget_id>   [--target .] [--version X]
cartograph uninstall <widget_id> [--target .]
cartograph upgrade <widget_id>   [--target .] [--version X]
cartograph status [widget_id]    [--target .]   omit widget_id to scan all installed
cartograph delete <widget_id>    [--confirm]    dry-run without --confirm
cartograph rollback <widget_id>  [--version X] [--reason "..."]

cartograph create <widget_id>
    --language python|javascript|nim       REQUIRED
    --domain backend|data|ml|security|infra|frontend|universal  REQUIRED

cartograph validate [path] [--lib]
cartograph checkin [path]
    --reason "what changed and why"       REQUIRED
    [--bump patch|minor|major]
    [--publish]                           also publish to cloud

cartograph rate <widget_id> <score 1-5>  [--comment "..."]
cartograph setup  [--agent claude|codex|gemini|antigravity|cursor]
                  [--write]
cartograph stats
cartograph doctor
cartograph dashboard

cartograph login   [--token TOKEN]
cartograph logout
cartograph whoami
cartograph cloud publish [widget_id] [path]  [--visibility public|private]
cartograph cloud unpublish <widget_id> [--confirm]
cartograph cloud sync
cartograph cloud rate <widget_id> <score 1-5> [--comment "..."]
```

## Development

```bash
pip install -e .
pytest
```

The widget library lives in your platform's user data directory and is seeded automatically on first run. To override the location, set `WIDGET_LIBRARY_PATH`. When running from source, a `Widget_Library/` directory alongside this repo takes precedence so local edits work without configuration.

Run `cartograph doctor` to check that all language engine dependencies (pytest, coverage, node, npx, vitest) are installed correctly.

## Architecture

```
cartograph/
  cli.py             Entry point - all commands
  engine.py          Core Cartograph class (search, load, orchestrate)
  validator.py       14-point validation pipeline
  checkin.py         Push edits back to library (versioning, contamination scan)
  installer.py       Install/uninstall/delete widgets
  inspector.py       Inspect widgets, read source and reviews
  cloud.py           Cloud registry client (search, publish, download, reviews)
  auth.py            OAuth credentials, token refresh, registry URL
  trust.py           HMAC-SHA256 stamp signing for push/verify
  dashboard.py       Local web UI (served via built-in HTTP server)
  scaffolding/       Widget scaffolding (create)
  languages/         Per-language engines (test runners, validators)
  search/            Hybrid BM25 + n-gram search
tests/               pytest suite
```

## Status

- Python: fully supported (create, validate, test, checkin)
- JavaScript/TypeScript: fully supported (React components, plain JS, vitest)
- Nim: fully supported (testament)
- Search: hybrid BM25 + n-gram (local and cloud)
- Cloud registry: live, with auth, publishing, versioning, reviews, and rollback
- Dashboard: `cartograph dashboard` opens a local web UI for browsing and managing widgets

## Cloud registry

The default registry is hosted by the Cartograph project. To point at your own registry instance, set `CARTOGRAPH_REGISTRY_URL`:

```bash
export CARTOGRAPH_REGISTRY_URL=https://your-registry.example.com
```

Authenticate with `cartograph login`, which opens a browser-based OAuth flow. Once authenticated, you can publish, rate, review, and roll back widgets.

## Roadmap

- More languages as validation pipelines are built and tested
- Registry federation and self-hosting documentation
