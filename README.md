# Cartograph

A widget library MCP server for AI agents. Search, install, create, validate, and check in validated reusable code widgets across languages.

## Why Cartograph

AI agents write a lot of code, but it disappears. Each new project starts from scratch, and agents can't naturally reuse logic across codebases without somewhere to put it.

Cartograph came out of a personal frustration. Features that took 10 to 20 hours to polish with AI coding tools would need to be rebuilt almost from scratch when the next project needed them. Once a shared library existed, those same features could be dropped into a new project in minutes.

Those same widgets have now been reused across many projects and have settled into a quiet loop of continuous improvement. Each time a new edge case surfaces, the fix goes back into the library, and every project that installs it going forward starts with that bug already squashed.

## Philosophy

AI coding operates with little oversight beyond what the user can catch. Our validation pipeline for widgets are built to ensure usable code gets saved into the library. We only ship what we can validate. That means Cartograph currently supports Python end-to-end: scaffolding, test running, coverage enforcement, contamination scanning, versioning, and checkin. Every widget that enters the library has passed all of those checks.

Supporting a language means owning its full validation pipeline, not just generating files. We'll add languages as those pipelines are ready, not before. All languages will use the same validation philophies as presented in the Python loop. If you have ideas for improving these pipelines, they are greatly appreciated.

## Quick Start

Install once:

```bash
pip install cartograph-mcp
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

### Other MCP clients (Cursor, Copilot, etc.)

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

Once the MCP is registered, ask your agent to set up instructions for the current project based on the mode you would like to use (see table below):

> "Set up Cartograph instructions in **developer** mode."

The agent calls `cartograph_setup`, which returns the right instruction text to append to your project's instruction file (CLAUDE.md, AGENTS.md, GEMINI.md, etc.). This lets you configure Cartograph per-project, so a consumer-facing app, an internal tool, and a library maintenance session can all behave differently without touching global settings.

Choose a mode based on how you want the agent to behave.

| Mode | Who it's for | What it does |
|---|---|---|
| `consumer` | Teams pulling from a shared library | Search before writing. Install and rate. No explicit widget authoring in design flow. |
| `developer` | Most local projects (recommended) | Search first + package reusable logic when you're done. |
| `maintainer` | Dedicated library agent | Audit existing widgets, improve low-rated ones, create new ones. |

Maintainer mode is worth running regularly. Think of it as weekly housekeeping for your library. The agent audits widgets, fixes issues surfaced by reviews, and improves anything that has drifted in quality. The value compounds over time: a well-maintained library means every future install starts from a higher baseline, bugs get squashed once and stay squashed, and the whole thing gets more useful the more you use it.

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

The widget library lives in your platform's user data directory and is seeded automatically on first run. To override the location, set `WIDGET_LIBRARY_PATH`. When running from source, a `Widget_Library/` directory alongside this repo takes precedence so local edits work without configuration.

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
