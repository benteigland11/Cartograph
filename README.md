# Cartograph

A widget library engine for AI agents. Search, install, create, validate, and check in reusable code widgets across languages.

## Install

```bash
pipx install /path/to/Cartograph
```

This installs the `cartograph` CLI into an isolated environment and makes it available globally.

For development (editable install):

```bash
pip install -e /path/to/Cartograph
```

The engine expects a `Widget_Library/` directory alongside the repo (or set `WIDGET_LIBRARY_PATH` env var).

## MCP Server

### Claude Code

Clone the repo and open it in Claude Code. The included `.mcp.json` registers the server automatically.

Or register manually:

```bash
claude mcp add --transport stdio cartograph -- cartograph
```

### Other MCP clients (Cursor, VS Code Copilot, Claude Desktop, etc.)

Add to the client's MCP config (location varies by client):

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

### HTTP mode (remote / shared access)

For running as a standalone server that multiple clients can connect to:

```bash
pip install -e "/path/to/Cartograph[http]"
cartograph --mode http --port 8742
```

Then point any MCP client at `http://localhost:8742/mcp/`.

## CLI

```bash
cartograph search "rate limiter"
cartograph install auth-middleware-python --target ./cartograph
cartograph create my-widget --language python --target ./widgets
cartograph validate ./widgets/my-widget/
cartograph checkin ./widgets/my-widget/ --reason "Initial release"
```

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

## v0.1 scope

- Python widgets fully supported (create, validate, test, checkin)
- Other languages scaffold but validation/testing is stubbed
- Search is local (BM25 + n-gram fuzzy matching)

## Tests

```bash
pytest
```
