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
