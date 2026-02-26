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
    from mcp.types import Tool, TextContent
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
        description="Install a widget into your project. Copies src/, tests/, examples/, and metadata to {target}/{widget_id}/.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"},
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
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"},
                "version": {"type": "string", "description": "Specific version to update to (defaults to latest)"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_uninstall",
        description="Remove an installed widget. Deletes {target}/{widget_id}/ and all its files.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"}
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
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"}
            },
            "required": ["widget_id", "target"]
        }
    ),
    Tool(
        name="cartograph_rate",
        description="Rate an installed widget. Must be installed at {target}/{widget_id}/.",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {"type": "string"},
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"},
                "score": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1-5 rating"},
                "comment": {"type": "string", "description": "What worked, what didn't (optional)"}
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
                    "enum": ["python", "javascript", "typescript", "go", "rust", "hip", "cpp", "c"]
                },
                "target": {"type": "string", "description": "Absolute path to the project's cartograph directory"}
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
