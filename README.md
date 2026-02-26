# Cartograph

A widget library MCP server for AI agents. Search, install, create, validate, and check in reusable code widgets across languages.

## Quick Start

### Claude Code

Clone the repo and open it in Claude Code. The included `.mcp.json` registers the server automatically.

Or register manually:

```bash
claude mcp add --transport stdio cartograph -- uvx --from /path/to/Cartograph cartograph
```

### Other MCP clients (Cursor, VS Code Copilot, Claude Desktop, etc.)

Add to the client's MCP config (location varies by client):

```json
{
  "mcpServers": {
    "cartograph": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "/path/to/Cartograph", "cartograph"]
    }
  }
}
```

### HTTP mode (remote / shared access)

```bash
uvx --from "/path/to/Cartograph[http]" cartograph --mode http --port 8742
```

Then point any MCP client at `http://localhost:8742/mcp/`.

## CLI

Also usable as a standalone CLI:

```bash
uvx --from /path/to/Cartograph cartograph search "rate limiter"
uvx --from /path/to/Cartograph cartograph install auth-middleware-python --target ./cartograph
uvx --from /path/to/Cartograph cartograph create my-widget --language python --target ./widgets
```

## Development

```bash
uv pip install -e /path/to/Cartograph
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
