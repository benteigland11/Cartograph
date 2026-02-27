# Cartograph

A widget library MCP server for AI agents. Search, install, create, validate, and check in reusable code widgets across languages.

## Why Cartograph

AI agents write a lot of code, but it disappears. Each new project starts from scratch, and agents don't naturally reuse logic across codebases without somewhere to put it.

Cartograph closes that loop. When an agent finishes a self-contained piece of logic, it packages it as a widget and checks it in. The next agent, on a different project or a different day, finds it, installs it, and rates it. Over time the library gets smarter: low-rated widgets get improved, high-rated ones get used more, and patterns that work keep spreading.

The rating system is built around integration friction, not subjective quality. A score answers one question: *how easy was this to plug in?* That signal is useful to agents making install decisions, and honest enough to be worth collecting.

## Philosophy

We only ship what we can fully validate. That means Cartograph currently supports Python end-to-end: scaffolding, test running, coverage enforcement, contamination scanning, versioning, and checkin. Every widget that enters the library has passed all of those checks.

Supporting a language means owning its full validation pipeline, not just generating files. We'll add languages as those pipelines are ready, not before.

## Quick Start

Install once:

```bash
pip install cartograph
```

Then register with your AI CLI:

### Claude Code

```bash
claude mcp add --scope user cartograph -- cartograph
```

Or just open this repo in Claude Code — the included `.mcp.json` registers it automatically.

### Codex

```bash
codex mcp add cartograph -- cartograph
```

### Gemini CLI

```bash
gemini mcp add --scope user cartograph cartograph
```

### Other MCP clients (Cursor, VS Code Copilot, Claude Desktop, etc.)

Add to the client's MCP config:

```json
{
  "mcpServers": {
    "cartograph": {
      "type": "stdio",
      "command": "cartograph"
    }
  }
}
```

### Project setup

Once the MCP is registered, ask your agent to set up instructions for the current project:

> "Set up Cartograph instructions in **developer** mode."

The agent calls `cartograph_setup`, which returns the right instruction text to append to your project's instruction file (CLAUDE.md, AGENTS.md, GEMINI.md, etc.). This lets you configure Cartograph per-project, so a consumer-facing app, an internal tool, and a library maintenance session can all behave differently without touching global settings.

Choose a mode based on how you want the agent to behave (see table below).

| Mode | Who it's for | What it does |
|---|---|---|
| `consumer` | Teams pulling from a shared library | Search before writing. Install and rate. No widget authoring. |
| `developer` | Most local projects (recommended) | Search first + package reusable logic when you're done. |
| `maintainer` | Dedicated library agent | Audit existing widgets, improve low-rated ones, create new ones. |

## CLI

Also usable as a standalone CLI:

```bash
cartograph search "rate limiter"
cartograph install auth-middleware-python --target /path/to/project
cartograph create my-widget --language python --target /path/to/project
```

## Development

```bash
pip install -e .
pytest
```

The engine expects a `Widget_Library/` directory alongside the repo (or set `WIDGET_LIBRARY_PATH` env var).

## Architecture

```
cartograph/
  engine.py          Core Cartograph class (search, load, orchestrate)
  server.py          MCP server (stdio + HTTP)
  validator.py       Widget validation against Gold Standards
  checkin.py         Push edits back to library (versioning, contamination scan)
  installer.py       Install/uninstall widgets into projects
  inspector.py       Inspect widgets, list popular
  scaffolding/       Widget scaffolding (create)
  languages/         Per-language engines (test runners, validators)
  search/            Hybrid BM25 + n-gram search
tests/               pytest suite
```

## Status

- Python: fully supported (create, validate, test, checkin)
- Search: local BM25 + n-gram fuzzy matching
- Registry: local

## Roadmap

- **More languages** as validation pipelines are built and tested
