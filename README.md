# Cartograph

[![Tests](https://github.com/benteigland11/Cartograph/actions/workflows/test.yml/badge.svg)](https://github.com/benteigland11/Cartograph/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/cartograph-cli?cacheSeconds=60)](https://pypi.org/project/cartograph-cli/)

A reusable local code registry for AI agents with optional cloud integration. Search, install, create, validate, and check in reusable code across projects. Only requires Python. Other languages in the repo are native validation scanners for their respective widget types.

## Why Cartograph

AI agents write a lot of code, but it disappears. Each new project starts from scratch, and agents can't naturally reuse logic across codebases without somewhere to put it.

Cartograph came out of a personal frustration. Features that took 10 to 20 hours to polish with AI coding tools would need to be rebuilt almost from scratch when the next project needed them and most of the hardened logic would be gone. Then I built a basic engine, and those same features could be dropped into a new project in minutes.

Those same widgets have now been reused across many projects and have settled into a quiet loop of continuous improvement. Each time a new edge case surfaces, the fix goes back into the library, and every project that installs it going forward starts with that bug already squashed.

## Philosophy

Something that might take getting used to is this CLI tool is made with agents in mind first. This means things like few interactive CLI commands.

We only ship what we can validate. Every widget that enters the library has passed a full pipeline: structure checks, manifest validation, coverage enforcement, contamination scanning, example execution, and versioning. If the pipeline can't run it, it doesn't go in.

Supporting a language means owning its full validation pipeline, not just generating files. We'll add languages as those pipelines are ready, not before.

Cloud version gets trickier. We ship this engine with the ability to self sign, and you can design the cloud service to accept a self signed or do its own validation. Default is not done in the cloud because that is an expensive operation.

## Quick Start

```bash
pip install cartograph-cli
```

Then generate instructions for your AI agent:

```bash
cartograph setup --agent claude --write
```

We built in the ability to separate out by agentic service in case some need different guidance.

## Commands

```
cartograph search <query>
    [--domain backend|data|ml|security|infra|frontend|universal]
    [--language python|javascript|typescript|nim]

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
    --language python|javascript|typescript|nim       REQUIRED
    --domain backend|data|ml|security|infra|frontend|universal  REQUIRED

cartograph validate [path] [--lib]
cartograph checkin [path]
    --reason "what changed and why"       REQUIRED
    [--bump patch|minor|major]
    [--publish]                           also publish to cloud

cartograph rate <widget_id> <score 1-5>  [--comment "..."]
    also works with @handle/widget-id for cloud widgets
cartograph setup  [--agent claude|codex|gemini|antigravity|cursor]
                  [--write] [--workflow [name]]
cartograph export [--output file.zip]        default: cartograph-library.zip
cartograph import <file.zip> [--force]       --force overwrites existing

cartograph config [key] [value]
cartograph stats
cartograph doctor
cartograph dashboard

cartograph login   [--token TOKEN]
cartograph logout
cartograph whoami
cartograph cloud publish [widget_id] [path]  [--visibility public|private]
                                             [--governance open|protected]
cartograph cloud unpublish <widget_id> [--confirm]
cartograph cloud settings <@handle/widget-id> [--governance open|protected]
cartograph cloud sync [--dry-run]
cartograph cloud proposals [widget_id] [proposal_id]
                           [--accept] [--reject] [--reason "..."]
```

## Development

```bash
pip install -e .
pytest
```

The widget library lives in your platform's user data directory. To override the location, set `WIDGET_LIBRARY_PATH`. When running from source, a `Widget_Library/` directory alongside this repo takes precedence so local edits work without configuration.

Run `cartograph doctor` to check that all language engine dependencies (pytest, coverage, node, npx, vitest) are installed correctly.

## Status

- Python: fully supported (create, validate, test, checkin)
- JavaScript: fully supported (React components, plain JS, vitest)
- Nim: fully supported (testament)
- Search: hybrid inverted index + n-gram with fuzzy resolution (local and cloud)
- Dashboard: `cartograph dashboard` opens a local web UI for browsing and managing widgets

## Cloud registry

The CLI tool is built around a local registry on your machine. It also supports an optional cloud registry for sharing widgets across teams or publicly.

The default hosted registry is in early development and may have rough edges. The local engine is production-ready and does not depend on cloud availability. If the registry is down or unreachable, everything local continues to work.

To point at your own registry instance, set `CARTOGRAPH_REGISTRY_URL`:

```bash
export CARTOGRAPH_REGISTRY_URL=https://your-registry.example.com
```

`cartograph login` opens a browser-based authentication flow provided by whichever registry you're connected to. Once authenticated, you can publish widgets. Setting a custom registry URL is a good fit for teams or enterprises that want this as an internal tool.

## Roadmap

- Continued support for more languages.
