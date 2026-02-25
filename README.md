# Cartographer

A widget library engine for AI agents. Search, install, create, validate, and check in reusable code widgets across languages.

## Setup

```bash
pip install -r requirements.txt
```

The engine expects a `Widget_Library/` and optional `Blueprints/` directory alongside it (or set `WIDGET_LIBRARY_PATH` / `BLUEPRINT_PATH` env vars).

## Usage

### As an MCP server (Claude Code)

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "cartographer": {
      "command": "python",
      "args": ["/path/to/cartographer_mcp.py"]
    }
  }
}
```

For HTTP mode (remote/shared access):

```bash
pip install starlette uvicorn
python cartographer_mcp.py --mode http --port 8742
```

### As a CLI

```bash
python cartographer.py search "rate limiter"
python cartographer.py install auth-middleware-python
python cartographer.py create my-widget --language python --domain backend
python cartographer.py validate ./cartographer/widgets/my-widget/
python cartographer.py checkin ./cartographer/widgets/my-widget/ --reason "Initial release"
```

## Architecture

```
cartographer.py        Core Cartographer class (search, load, orchestrate)
cartographer_mcp.py    MCP server wrapper (stdio + HTTP)
validator.py           Widget validation against Gold Standards
checkin.py             Push edits back to library (contamination scan, versioning)
installer.py           Install/uninstall widgets into projects
inspector.py           Inspect widgets, list popular
scaffolding/           Widget/blueprint scaffolding (create)
languages/             Per-language engines (test runners, validators)
search/                Hybrid BM25 + n-gram search
library_config.json    Domain definitions, language rules
tests/                 pytest suite
```

## v0.1 scope

- Python widgets fully supported (create, validate, test, checkin)
- Other languages scaffold but validation/testing is stubbed
- Search is local (BM25 + n-gram fuzzy matching)

## Tests

```bash
pytest
```
