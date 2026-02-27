#!/usr/bin/env python3
"""
Cartograph MCP Server

Exposes Cartograph's widget management as MCP tools for AI agents.

Usage:
    cartograph                    # after pip install
    python -m cartograph          # from source

Add to Claude Code settings (~/.claude/settings.json):
    {
      "mcpServers": {
        "cartograph": {
          "command": "cartograph",
          "env": {"WIDGET_LIBRARY_PATH": "/path/to/Widget_Library"}
        }
      }
    }
"""

import sys
import json
import asyncio
import logging

log = logging.getLogger("cartograph")

# Import MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool, TextContent,
        Prompt, PromptMessage, GetPromptResult,
        Resource, TextResourceContents,
    )
except ImportError:
    print("MCP SDK not installed. Run: pip install cartograph", file=sys.stderr)
    sys.exit(1)

# Import Cartograph engine
from .engine import Cartograph, LIBRARY_PATH

# Initialize server
server = Server("cartograph")


_carto_instance = None

def get_carto():
    """Get a cached Cartograph instance.

    Skips installed-index scan (MCP handlers rescan with the correct
    project target when they need it).  The library is loaded once and
    the search index is built once per server lifetime.
    """
    global _carto_instance
    if _carto_instance is None:
        _carto_instance = Cartograph(
            LIBRARY_PATH, search_backend='meilisearch')
    return _carto_instance


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

TOOLS = [
    # -- Discovery --
    Tool(
        name="cartograph_search",
        description="Search the Cartograph widget library. Returns relevance-ranked results.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string", "description": "Filter by language (e.g., 'python', 'typescript', 'rust')"},
                "domain": {
                    "type": "string",
                    "enum": ["backend", "data", "ml", "security", "infra", "frontend", "universal"],
                    "description": "Filter by domain"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="cartograph_inspect",
        description="Inspect a widget before installing. Returns examples, rating, and recent versions. Use flags for source code, full version history, or reviews.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "show_source": {"type": "boolean", "default": False, "description": "Include source code"},
                "show_all_versions": {"type": "boolean", "default": False, "description": "Show full version history instead of last 5"},
                "show_reviews": {"type": "boolean", "default": False, "description": "Include full review text"}
            },
            "required": ["widget_id"]
        }
    ),
    # -- Project --
    Tool(
        name="cartograph_install",
        description="Install a widget into your project. Copies src/, tests/, examples/, and metadata to {target}/cartograph/{widget_id}/.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project root"},
                "version": {"type": "string", "description": "Specific version to install (defaults to latest)"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_update",
        description="Update an installed widget to the latest version (or a specific version).",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project root"},
                "version": {"type": "string", "description": "Specific version to update to (defaults to latest)"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_uninstall",
        description="Remove an installed widget. Deletes {target}/cartograph/{widget_id}/ and all its files.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project root"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_status",
        description="Check if an installed widget is outdated or locally modified.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project root"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_rate",
        description="Rate an installed widget. Must be installed at {target}/cartograph/{widget_id}/.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project root"},
                "score": {
                    "type": "integer", "minimum": 1, "maximum": 5,
                    "description": "How easy was this to plug in? 1 = broken/unusable, 2 = needed heavy modification, 3 = needed some fixes, 4 = minor adjustments only, 5 = drop-in, worked as-is"
                },
                "comment": {"type": "string", "description": "One specific thing: what made integration easy, what you had to change, or what surprised you (optional)"}
            },
            "required": ["widget_id", "target", "score"]
        }
    ),

    # -- Authoring --
    Tool(
        name="cartograph_create",
        description="Scaffold a new widget with language-specific starter code, tests, and examples.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string", "description": "Widget ID (e.g., 'logic-retry-backoff'). Language suffix auto-appended."},
                "language": {
                    "type": "string",
                    "enum": ["python"]
                },
                "target": {"type": "string", "description": "Absolute path to the project root"}
            },
            "required": ["widget_id", "language", "target"]
        }
    ),
    Tool(
        name="cartograph_validate",
        description="Validate a widget's structure, metadata, and tests.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the widget directory"}
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="cartograph_checkin",
        description="Validate and submit a widget to the library. Runs all checks, bumps version on updates, and adds to the searchable index.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the widget directory"},
                "reason": {"type": "string", "description": "Changelog entry (e.g., 'Add retry with exponential backoff')"},
                "version_bump": {
                    "type": "string",
                    "enum": ["minor", "major", "patch"],
                    "description": "How to bump version on update (default: minor). Ignored on first checkin."
                },
                "override_warnings": {
                    "type": "boolean",
                    "description": "Set to true to proceed despite warnings (e.g., possible credentials in tests). Requires override_reason."
                },
                "override_reason": {
                    "type": "string",
                    "description": "Explanation for why warnings are being overridden (e.g., 'credentials are fake test fixtures')."
                }
            },
            "required": ["path", "reason"]
        }
    ),
]


# ============================================================================
# PROMPT DEFINITIONS
# ============================================================================

_WORKFLOW_CREATE = """\
You are authoring a new Cartograph widget. Follow this workflow exactly:

1. SEARCH FIRST — cartograph_search to check if something similar exists.
   If it does, consider extending it via checkin instead of creating new.

2. CREATE — cartograph_create with:
   - widget_id: <domain>-<name> (e.g. logic-retry-backoff, data-csv-parser)
   - language: python
   - target: absolute path to the project root
   Widget lands at <target>/cartograph/<widget_id>-python/

3. IMPLEMENT — write the real logic in src/. Rules:
   - Zero external dependencies unless declared in widget.json tech_stack.dependencies
   - Type hints on all public functions
   - No global state, no hardcoded paths, no project-specific code

4. TEST — write thorough tests in tests/. Rules:
   - pytest only, no unittest
   - No __init__.py in tests/
   - Target 80%+ coverage — the validator enforces this
   - Mock stdin/network/filesystem where needed

5. EXAMPLE — write examples/example_usage.py. Rules:
   - Must run and exit cleanly with no user input
   - Use hardcoded/fake data only
   - Demonstrate the primary API

6. VALIDATE — cartograph_validate <widget_path>
   Fix every issue before proceeding. Common failures:
   - Coverage too low → add tests
   - Example fails → check for interactive input or missing imports
   - Contamination → remove absolute paths or credentials from src/

7. CHECKIN — cartograph_checkin with a clear reason describing what it does.
   On success, rate yourself: cartograph_rate (score 1-5, honest comment).
"""

_WORKFLOW_INSTALL = """\
You are installing a Cartograph widget into a project. Follow this workflow:

1. SEARCH — cartograph_search with a natural language query describing what you need.
   Try multiple queries if first results are poor (synonyms, shorter queries).

2. INSPECT — cartograph_inspect on promising results to see:
   - Source code (show_source: true)
   - Reviews and ratings
   - Examples of usage

3. INSTALL — cartograph_install with:
   - widget_id: the widget ID from search results
   - target: absolute path to the project root
   Widget lands at <target>/cartograph/<widget_id>/

4. USE — import from cartograph/<widget_id>/src/
   Check the examples/ directory for usage patterns.

5. RATE — cartograph_rate after using it.
   Be honest: score reflects how easy it was to plug in, not whether you like it.
   Leave a comment about what worked, what you changed, or what surprised you.

6. UPDATE (if needed) — cartograph_status to check if outdated.
   cartograph_update to pull the latest version.
"""

_WORKFLOW_MAINTAIN = """\
You are maintaining Cartograph widgets in a project. Follow this workflow:

1. CHECK STATUS — cartograph_status for each installed widget.
   Look for: outdated (new version available), modified (local changes differ from library).

2. REVIEW CHANGES — cartograph_inspect <widget_id> show_all_versions: true
   Read the changelog to understand what changed before updating.

3. UPDATE — cartograph_update if the new version looks safe.
   Your local modifications will be overwritten — back them up first if needed.

4. CONTRIBUTE BACK — if you fixed a bug or improved a widget locally,
   check it back in: cartograph_checkin with a clear reason.
   Your fix helps everyone using that widget.
"""

PROMPTS = [
    Prompt(name="create-widget",    description="Step-by-step workflow for authoring and publishing a new widget"),
    Prompt(name="install-widget",   description="Step-by-step workflow for finding, installing, and rating a widget"),
    Prompt(name="maintain-widgets", description="Step-by-step workflow for checking status, updating, and contributing fixes"),
]

# ============================================================================
# RESOURCE DEFINITIONS  — instruction snippets for each AI environment
# ============================================================================

_INSTRUCTIONS_BASE = """\
## Cartograph

Cartograph is a widget library MCP server. Widgets are reusable, self-contained
code modules that live in your project under cartograph/<widget_id>/.

### As a consumer
Before writing new utility code, search the library first:
- cartograph_search — find existing widgets
- cartograph_install — install to project root (widgets land in cartograph/)
- cartograph_rate — rate after using (honest score + one specific comment)
- cartograph_status / cartograph_update — keep widgets current

### As an author
When you write code that could be reused across projects, package it:
- cartograph_create — scaffold a new widget in this project
- Build the logic, write tests (80%+ coverage), write a non-interactive example
- cartograph_validate — must pass before checkin
- cartograph_checkin — publish to the library

### Widget IDs
Format: <domain>-<name>-<language>  e.g. logic-retry-backoff-python
Domains: backend, data, ml, security, infra, frontend, universal

### Workflows
Use MCP prompts for detailed step-by-step guidance:
- /mcp__cartograph__create-widget
- /mcp__cartograph__install-widget
- /mcp__cartograph__maintain-widgets
"""

_INSTRUCTIONS_CLAUDE = _INSTRUCTIONS_BASE.replace(
    "- /mcp__cartograph__create-widget\n"
    "- /mcp__cartograph__install-widget\n"
    "- /mcp__cartograph__maintain-widgets",
    "Type these in chat to load the full workflow:\n"
    "- /mcp__cartograph__create-widget\n"
    "- /mcp__cartograph__install-widget\n"
    "- /mcp__cartograph__maintain-widgets"
)

_INSTRUCTIONS_CODEX   = _INSTRUCTIONS_BASE
_INSTRUCTIONS_GEMINI  = _INSTRUCTIONS_BASE

RESOURCES = [
    Resource(
        uri="cartograph://instructions/claude",
        name="Cartograph instructions for Claude Code (CLAUDE.md)",
        description="Paste into your project's CLAUDE.md to guide Claude on every turn",
        mimeType="text/plain",
    ),
    Resource(
        uri="cartograph://instructions/codex",
        name="Cartograph instructions for Codex (AGENTS.md)",
        description="Paste into your project's AGENTS.md to guide Codex on every turn",
        mimeType="text/plain",
    ),
    Resource(
        uri="cartograph://instructions/gemini",
        name="Cartograph instructions for Gemini CLI (GEMINI.md)",
        description="Paste into your project's GEMINI.md to guide Gemini on every turn",
        mimeType="text/plain",
    ),
]

_RESOURCE_CONTENT = {
    "cartograph://instructions/claude": _INSTRUCTIONS_CLAUDE,
    "cartograph://instructions/codex":  _INSTRUCTIONS_CODEX,
    "cartograph://instructions/gemini": _INSTRUCTIONS_GEMINI,
}


# ============================================================================
# TOOL HANDLERS
# ============================================================================

@server.list_tools()
async def list_tools():
    """Return list of available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""

    try:
        if name == "cartograph_search":
            result = get_carto().search(
                query=arguments["query"],
                domain_filter=arguments.get("domain"),
                language_filter=arguments.get("language"),
            )

        elif name == "cartograph_inspect":
            result = get_carto().inspect(
                widget_id=arguments["widget_id"],
                show_source=arguments.get("show_source", False),
                show_all_versions=arguments.get("show_all_versions", False),
                show_reviews=arguments.get("show_reviews", False),
            )

        elif name == "cartograph_install":
            result = get_carto().install(
                widget_id=arguments["widget_id"],
                target_dir=arguments["target"],
                version=arguments.get("version"),
            )

        elif name == "cartograph_validate":
            result = get_carto().validate_item(path=arguments["path"])

        elif name == "cartograph_create":
            result = get_carto().create(
                item_id=arguments["widget_id"],
                language=arguments["language"],
                target_dir=arguments["target"],
            )

        elif name == "cartograph_checkin":
            result = get_carto().checkin(
                path=arguments["path"],
                reason=arguments["reason"],
                version_bump=arguments.get("version_bump", "minor"),
                override_warnings=arguments.get("override_warnings", False),
                override_reason=arguments.get("override_reason"),
            )

        elif name == "cartograph_status":
            result = get_carto().widget_status(
                widget_id=arguments["widget_id"],
                target_dir=arguments["target"],
            )

        elif name == "cartograph_update":
            result = get_carto().update(
                widget_id=arguments["widget_id"],
                target_dir=arguments["target"],
                version=arguments.get("version"),
            )

        elif name == "cartograph_uninstall":
            result = get_carto().uninstall(
                widget_id=arguments["widget_id"],
                target_dir=arguments["target"],
            )

        elif name == "cartograph_rate":
            result = get_carto().add_review(
                widget_id=arguments["widget_id"],
                target_dir=arguments["target"],
                score=arguments["score"],
                comment=arguments.get("comment"),
            )

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        error_result = {"error": str(e)}
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


# ============================================================================
# PROMPT HANDLERS
# ============================================================================

@server.list_prompts()
async def list_prompts():
    return PROMPTS


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None):
    workflows = {
        "create-widget":    _WORKFLOW_CREATE,
        "install-widget":   _WORKFLOW_INSTALL,
        "maintain-widgets": _WORKFLOW_MAINTAIN,
    }
    text = workflows.get(name)
    if not text:
        raise ValueError(f"Unknown prompt: {name}")
    return GetPromptResult(
        description=next(p.description for p in PROMPTS if p.name == name),
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )


# ============================================================================
# RESOURCE HANDLERS
# ============================================================================

@server.list_resources()
async def list_resources():
    return RESOURCES


@server.read_resource()
async def read_resource(uri: str):
    content = _RESOURCE_CONTENT.get(str(uri))
    if not content:
        raise ValueError(f"Unknown resource: {uri}")
    return TextResourceContents(uri=str(uri), mimeType="text/plain", text=content)


# ============================================================================
# MAIN
# ============================================================================

async def run_stdio():
    """Run the MCP server in stdio mode (for Claude Code)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_http(host: str = "0.0.0.0", port: int = 8742):
    """Run the MCP server in HTTP mode (recommended for remote servers)."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse
    from contextlib import asynccontextmanager
    import uvicorn

    # Create the session manager (stateless for simpler client connections)
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
    )

    @asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    async def health_handler(request):
        return JSONResponse({"status": "healthy", "service": "cartograph"})

    app = Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[
            # Mount the session manager as an ASGI sub-application
            Mount("/mcp", app=session_manager.handle_request),
            Route("/health", health_handler),
        ]
    )

    log.info("Cartograph MCP Server running at http://%s:%d", host, port)
    log.info("  MCP endpoint: http://%s:%d/mcp", host, port)
    log.info("  Health check: http://%s:%d/health", host, port)
    uvicorn.run(app, host=host, port=port)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Cartograph MCP Server")
    parser.add_argument(
        "--mode",
        choices=["stdio", "http"],
        default="stdio",
        help="Server mode: stdio (for Claude Code subprocess) or http (standalone HTTP server)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP mode")
    parser.add_argument("--port", type=int, default=8742, help="Port for HTTP mode")

    args = parser.parse_args()

    if args.mode == "stdio":
        asyncio.run(run_stdio())
    else:
        run_http(args.host, args.port)


if __name__ == "__main__":
    main()
