# Cartograph

A widget library MCP server for AI agents. Search, install, create, validate, and check in reusable code widgets across languages.

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

Then ask your agent: **"Set up Cartograph instructions for this project."**
It will call `cartograph_setup` and add the right instructions to your project's instruction file.

Choose a mode based on how you want your agent to behave:

| Mode | Who it's for | What it does |
|---|---|---|
| `consumer` | Teams pulling from a shared library | Search before writing. Install and rate. No widget authoring. |
| `developer` | Default for local projects | Search first + package reusable logic when you're done. |
| `maintainer` | Dedicated library agent | Audit existing widgets, improve low-rated ones, create new ones. |

Example prompt: **"Set up Cartograph in developer mode."**

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

- Python widgets fully supported (create, validate, test, checkin)
- Other languages scaffold but validation/testing is stubbed
- Search is local (BM25 + n-gram fuzzy matching)
