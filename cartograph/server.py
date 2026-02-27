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
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10). Low-relevance results are always filtered out regardless of limit."
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

    # -- Setup --
    Tool(
        name="cartograph_setup",
        description=(
            "Get Cartograph setup instructions for your project. "
            "Call this once per project to get the text to add to your instruction file "
            "(CLAUDE.md, AGENTS.md, GEMINI.md, etc.).\n\n"
            "Modes:\n"
            "  consumer   — search and install only; no widget authoring\n"
            "  developer  — search before writing + package reusable logic (default)\n"
            "  maintainer — library steward: audit, improve, and create widgets"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "enum": ["claude", "codex", "gemini", "other"],
                    "description": "Your AI environment. Use 'other' if not listed."
                },
                "mode": {
                    "type": "string",
                    "enum": ["consumer", "developer", "maintainer"],
                    "description": "How this agent should interact with Cartograph. Defaults to 'developer'."
                }
            },
            "required": ["environment"]
        }
    ),
]


# ============================================================================
# PROMPT DEFINITIONS
# ============================================================================

_WORKFLOW_CHECKIN = """\
You have finished writing a piece of logic. Before moving on, ask:
"Could this work in another project without modification?"

If yes, package it as a widget now while the context is fresh.

1. CREATE scaffold — cartograph_create with:
   - widget_id: <domain>-<name> (e.g. logic-retry-backoff, data-csv-parser)
   - language: python
   - target: absolute path to the project root
   Widget lands at <target>/cartograph/<widget_id>-python/

2. COPY your code into src/. Clean it up:
   - Remove anything project-specific (imports, paths, config, assumptions)
   - Add type hints to all public functions
   - No global state, no hardcoded values
   - Declare any third-party dependencies in widget.json tech_stack.dependencies

3. WRITE TESTS in tests/:
   - pytest only, no unittest, no __init__.py in tests/
   - 80%+ coverage — the validator enforces this
   - Mock stdin/network/filesystem where needed

4. WRITE EXAMPLE in examples/example_usage.py:
   - Must run and exit cleanly with no user input
   - Use hardcoded/fake data, demonstrate the primary API

5. VALIDATE — cartograph_validate <widget_path>
   Fix every issue. Common failures:
   - Coverage too low → add tests
   - Example fails → remove interactive input or missing imports
   - Contamination → remove absolute paths or credentials from src/

6. CHECKIN — cartograph_checkin with a one-line reason.

7. RATE — cartograph_rate (honest score, one specific comment).
"""

_WORKFLOW_INSTALL = """\
You need a piece of reusable code. Search before writing it yourself.

1. SEARCH — cartograph_search with a natural language query.
   Try short queries, synonyms, or domain terms if first results are poor.

2. INSPECT — cartograph_inspect on anything promising:
   - show_source: true to read the actual code
   - show_reviews: true to see what others ran into

3. INSTALL — cartograph_install:
   - widget_id: from search results
   - target: absolute path to the project root
   Widget lands at <target>/cartograph/<widget_id>/

4. USE — import from cartograph/<widget_id>/src/
   Check examples/ for usage patterns.

5. RATE — cartograph_rate after using it.
   Score = how easy was it to plug in (1-5).
   Comment = one specific thing: what worked, what you changed, or what surprised you.
"""

_WORKFLOW_MAINTAIN = """\
You are updating or contributing back to installed widgets.

1. CHECK STATUS — cartograph_status for each installed widget.
   Outdated = new version in library. Modified = your local copy differs.

2. BEFORE UPDATING — cartograph_inspect show_all_versions: true
   Read the changelog. Understand what changed.

3. UPDATE — cartograph_update pulls the latest version.
   Warning: overwrites local changes. Back up modifications first if needed.

4. CONTRIBUTE BACK — fixed a bug or improved a widget?
   cartograph_checkin with a clear reason. Your fix goes into the library
   and helps everyone using that widget.
"""

PROMPTS = [
    Prompt(name="checkin-widget",   description="Workflow for packaging finished code as a reusable widget and checking it in"),
    Prompt(name="install-widget",   description="Workflow for finding, installing, and rating a widget"),
    Prompt(name="maintain-widgets", description="Workflow for updating installed widgets and contributing fixes back"),
]

# ============================================================================
# INSTRUCTION CONTENT — mode × environment
# ============================================================================

# Per-mode base instructions
_MODE_CONSUMER = """\
## Cartograph

Cartograph is a shared widget library. Widgets are reusable, self-contained
code modules. They live in your project under cartograph/<widget_id>/.

### One rule: search before writing reusable code

Before implementing anything self-contained (a UI component, a parser, a retry
helper, a data pipeline, a formatter), run cartograph_search. If something
useful exists, install and use it instead of writing from scratch.

### Core tools
- cartograph_search — search the library
- cartograph_inspect — read source and reviews before installing
- cartograph_install — install a widget (target = project root)
- cartograph_rate — rate after using (honest score + one comment)
"""

_MODE_DEVELOPER = """\
## Cartograph

Cartograph is a shared widget library. Widgets are reusable, self-contained
code modules. They live in your project under cartograph/<widget_id>/.

### Two rules to follow on every task

**1. Search before writing reusable code.**
Before implementing anything self-contained (a UI component, a parser, a retry
helper, a data pipeline, a formatter), run cartograph_search. If something
useful exists, install and use it instead of writing from scratch.

**2. Spot generalizable work as you go and suggest it to the user.**
As you write code, watch for logic that has no project-specific assumptions —
a clean abstraction, a handy formatter, a robust error handler. When you notice
one, suggest packaging it: "This would work well as a widget — it'll be easier
to test, improve, and reuse across projects. Want me to package it?"
Let the user decide. If they say yes, do it before moving on while the context
is fresh.

### Editing installed widgets
Do not edit files inside cartograph/<widget_id>/ directly. They are shared
code and local edits will be overwritten if the widget is updated.

- If the widget's behavior doesn't fit your needs, wrap or extend it in your
  own project code rather than modifying the widget source.
- If you find a bug or a genuine improvement, fix it and use cartograph_checkin
  to contribute it back. The fix goes into the library and benefits every
  project using that widget.
- cartograph_status will tell you if your local copy has drifted from the
  library version.

### Core tools
- cartograph_search — search the library
- cartograph_install — install a widget (target = project root)
- cartograph_rate — rate after using (required: honest score + one comment)
- cartograph_checkin — contribute a fix back to the library
- cartograph_validate — validate before checkin (must pass)
"""

_MODE_MAINTAINER = """\
## Cartograph — Maintainer Mode

Your role is library steward. Your primary goal is the health and growth of
the widget library, not project feature work.

### What to do each session

**1. Audit existing widgets.**
cartograph_search to browse, cartograph_inspect show_reviews: true to read feedback.
- Low rating or negative reviews → fix the issue and checkin an improvement
- Broken examples → fix them
- Low test coverage → add tests

**2. Improve low-rated widgets.**
Read the reviews. Find the friction. Fix it, bump the version, write a clear
changelog entry in cartograph_checkin.

**3. Create new widgets for recurring patterns.**
If a pattern keeps appearing across projects but isn't in the library, build it.
cartograph_create → develop → validate → checkin.

Every change must go through cartograph_validate and cartograph_checkin before
it counts. Edits that stay local help nobody.

### Core tools (full access)
- cartograph_search / cartograph_inspect
- cartograph_create / cartograph_validate / cartograph_checkin
- cartograph_status / cartograph_update / cartograph_rate
"""

# Per-environment suffix appended to any mode's instructions
_ENV_PROMPT_SUFFIX = {
    "claude": """\

### Detailed workflows (load on demand)
Type in chat:
- /mcp__cartograph__install-widget
- /mcp__cartograph__checkin-widget
- /mcp__cartograph__maintain-widgets
""",
    "codex": "",
    "gemini": "",
    "other": "",
}

_MODE_INSTRUCTIONS = {
    "consumer":   _MODE_CONSUMER,
    "developer":  _MODE_DEVELOPER,
    "maintainer": _MODE_MAINTAINER,
}


def _build_instructions(mode: str, environment: str) -> str:
    base = _MODE_INSTRUCTIONS.get(mode, _MODE_DEVELOPER)
    suffix = _ENV_PROMPT_SUFFIX.get(environment, "")
    return base + suffix


# ============================================================================
# RESOURCE DEFINITIONS  — kept for MCP resource protocol compatibility
# ============================================================================

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
    "cartograph://instructions/claude": _build_instructions("developer", "claude"),
    "cartograph://instructions/codex":  _build_instructions("developer", "codex"),
    "cartograph://instructions/gemini": _build_instructions("developer", "gemini"),
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
                top_k=arguments.get("limit", 10),
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

        elif name == "cartograph_setup":
            env  = arguments["environment"]
            mode = arguments.get("mode", "developer")
            instructions = _build_instructions(mode, env)
            file_hint = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md"}.get(env, "your instruction file")
            result = {
                "instructions": instructions,
                "note": f"Append the above text to {file_hint} in your project root.",
            }

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
        "checkin-widget":   _WORKFLOW_CHECKIN,
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
