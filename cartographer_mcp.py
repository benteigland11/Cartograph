#!/usr/bin/env python3
"""
Cartographer MCP Server

Exposes Cartographer's widget/blueprint management as MCP tools for AI agents.

Usage:
    python cartographer_mcp.py

Add to Claude Code settings (~/.claude/settings.json):
    {
      "mcpServers": {
        "cartographer": {
          "command": "python",
          "args": ["/path/to/cartographer_mcp.py"]
        }
      }
    }
"""

import sys
import os
import json
import asyncio

# Ensure we can import from the same directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import Cartographer
from cartographer import Cartographer, LIBRARY_PATH, BLUEPRINT_PATH

# Initialize server
server = Server("cartographer")


def get_carto():
    """Get a fresh Cartographer instance to ensure library is up-to-date.

    Uses Meilisearch backend for typo-tolerant, fast search.
    Falls back to BM25 if Meilisearch is unavailable.
    """
    return Cartographer(LIBRARY_PATH, BLUEPRINT_PATH, search_backend='meilisearch')


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

TOOLS = [
    Tool(
        name="cartographer_search",
        description="""Search the Cartographer library for widgets and blueprints.

FEATURES:
  - Typo-tolerant (powered by Meilisearch) - 'authentcation' finds 'authentication'
  - Returns relevance-ranked results with scores
  - Filters by domain, language, and type

RESPONSE FIELDS:
  - installed: Widgets already in your project (id, name, version, path)
  - library: Available widgets (id, name, description, tags, rating, install_count, etc.)

TIPS:
  - Use specific terms: 'jwt auth' > 'authentication'
  - Check install_count and rating for popular/proven widgets
  - Blueprints orchestrate multiple widgets together""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms - typo-tolerant (e.g., 'auth', 'sqlite store', 'rate limiter')"
                },
                "domain": {
                    "type": "string",
                    "enum": ["backend", "data", "ml", "security", "infra", "frontend", "universal", "all"],
                    "default": "all",
                    "description": "Filter by domain"
                },
                "language": {
                    "type": "string",
                    "description": "Filter by language (e.g., 'python', 'javascript', 'typescript', 'rust', 'go')"
                },
                "type": {
                    "type": "string",
                    "enum": ["widget", "blueprint", "all"],
                    "default": "all",
                    "description": "Filter by type - widgets are reusable code, blueprints are orchestration patterns"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="cartographer_inspect",
        description="""Get detailed information about a widget or blueprint before installing.

DEFAULT RESPONSE (no flags):
  - Metadata: id, name, version, description, tags, domain
  - Tech stack: language, dependencies
  - Integration guide: usage instructions, constraints
  - Stats: rating, install_count, test_count

OPTIONAL CONTENT (use flags to include):
  - show_source: Full source code from src/
  - show_examples: Usage examples from examples/
  - show_tests: Test code from tests/
  - show_all: All of the above

WORKFLOW:
  1. search → find candidates
  2. inspect → review details (use show_examples to see usage patterns)
  3. install → add to project""",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {
                    "type": "string",
                    "description": "ID of the widget/blueprint to inspect (from search results)"
                },
                "show_source": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include full source code"
                },
                "show_examples": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include usage examples (recommended before install)"
                },
                "show_tests": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include test code"
                },
                "show_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include source, examples, and tests"
                }
            },
            "required": ["widget_id"]
        }
    ),
    Tool(
        name="cartographer_install",
        description="""Install a widget or blueprint into your project.

WHAT HAPPENS:
  1. Copies entire widget directory to: ./{target}/{widget_id}/
  2. Includes src/, tests/, examples/, and all metadata
  3. Tracks installation in local index for updates/uninstall
  4. For blueprints: auto-installs all composed widgets into the blueprint's widgets/ subdirectory

BLUEPRINT-TARGETED INSTALL:
  Use the 'blueprint' parameter to install a widget INTO a blueprint's widgets/ subdirectory.
  This also updates the blueprint's composed_of with a pinned version entry.

SELF-CONTAINED BLUEPRINTS:
  When installing a blueprint from the library, composed widgets are installed inside the
  blueprint directory (not in top-level widgets/), keeping the blueprint self-contained.

AFTER INSTALL:
  - Import from: {target}/{widget_id}/src/
  - Run tests: pytest {target}/{widget_id}/tests/
  - See examples: {target}/{widget_id}/examples/

TYPICAL WORKFLOW:
  1. search → find widget
  2. inspect → review code/examples
  3. install → add to project
  4. rate → provide feedback after use""",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {
                    "type": "string",
                    "description": "ID of the widget/blueprint to install (from search results)"
                },
                "target": {
                    "type": "string",
                    "default": "cartographer",
                    "description": "Target directory for installation. IMPORTANT: Use an absolute path (e.g., '/home/user/myproject/cartographer') since the MCP server resolves relative paths from its own location, not your project."
                },
                "version": {
                    "type": "string",
                    "description": "Specific version to install (optional, defaults to latest)"
                },
                "blueprint": {
                    "type": "string",
                    "description": "Blueprint ID/folder to install this widget into. Installs to the blueprint's widgets/ subdirectory and updates composed_of."
                }
            },
            "required": ["widget_id"]
        }
    ),
    Tool(
        name="cartographer_validate",
        description="""Validate a local widget or blueprint against Gold Standards. Use this before checkin to catch issues early.

CHECKS PERFORMED:
  1. Directory structure (widget.json, src/, tests/, examples/)
  2. widget.json schema validation
  3. Source files exist and are non-empty
  4. Test files exist and all tests pass (pytest)
  5. Example files exist

Returns detailed error messages for any failures. Fix all issues before running checkin.""",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the widget/blueprint directory to validate"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="cartographer_create",
        description="""Create a new widget or blueprint with starter files.

WIDGETS: Creates a ready-to-edit widget with compilable/runnable skeleton code.
  Requires 'language' parameter. Creates src/, tests/, examples/, widget.json.

BLUEPRINTS: Creates a blueprint shell for composing widgets together.
  Set item_type="blueprint". No language required. Creates src/, examples/, widgets/, blueprint.json.
  Use cartographer_install with 'blueprint' param to add widgets into it.

SUPPORTED LANGUAGES (widgets only):
  - python, javascript, typescript, go, rust

ID NAMING CONVENTION:
  - Widgets: {category}-{name} (language suffix auto-appended)
    Examples: logic-retry-backoff, ui-modal-dialog
  - Blueprints: workflow-{name}
    Examples: workflow-auth, workflow-payment

DEFAULT TARGET:
  - Widgets: ./cartographer/widgets/{item_id}/
  - Blueprints: ./cartographer/blueprints/{item_id}/""",
        inputSchema={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "ID for the widget/blueprint. Use format: {category}-{name} (e.g., 'logic-retry-backoff' for widgets, 'workflow-auth' for blueprints)."
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "typescript", "go", "rust", "hip", "cpp", "c"],
                    "description": "Programming language for the widget. Required for widgets, not needed for blueprints. Use 'hip' for AMD HIP kernels, 'cpp' for C++, 'c' for plain C."
                },
                "item_type": {
                    "type": "string",
                    "enum": ["widget", "blueprint"],
                    "default": "widget",
                    "description": "Type of item to create. Use 'blueprint' to create a blueprint shell."
                },
                "composed_of": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Widget IDs to compose (for blueprints). Optional - can start empty and add widgets later via install."
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name (optional, derived from ID if not provided)"
                },
                "domain": {
                    "type": "string",
                    "enum": ["backend", "data", "ml", "security", "infra", "frontend", "universal"],
                    "default": "backend",
                    "description": "Widget/blueprint domain"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for searchability (e.g., ['retry', 'backoff'])"
                },
                "target": {
                    "type": "string",
                    "description": "Target directory (default: ./cartographer/widgets/<item_id> or ./cartographer/blueprints/<item_id>)"
                },
                "gpu_targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GPU architecture codes this widget targets (e.g., ['gfx1100', 'gfx1200']). For HIP/GPU widgets."
                },
                "widget_type": {
                    "type": "string",
                    "enum": ["library", "kernel", "patch", "probe"],
                    "description": "Widget subtype. 'kernel' for GPU kernels, 'patch' for codebase patches, 'probe' for diagnostics, 'library' (default) for reusable code."
                }
            },
            "required": ["item_id"]
        }
    ),
    Tool(
        name="cartographer_checkin",
        description="""Validate and submit a widget/blueprint to the library.

VALIDATION CHECKS:
  1. Structure: widget.json, src/, tests/, examples/ all present
  2. Metadata: Valid widget.json with required fields
  3. Tests: All tests must pass (runs pytest)
  4. Code quality: Source files exist and are non-empty
  5. Duplicates: Checks for similar existing widgets

COMMON FAILURES:
  - Missing widget.json or required directories
  - Tests failing or no test files
  - Empty src/ directory
  - Invalid widget.json schema

INSTALL DIR SUPPORT:
  Works directly from installed widget paths (cartographer/widgets/ or cartographer/blueprints/).
  When checking in from an install directory, the source copy is left in place (not moved/archived).

VERSION BUMPING:
  On updates (not first checkin), the version is auto-bumped before archiving/changelog.
  Use version_bump to control: "minor" (default, X.Y+1.0), "major" (X+1.0.0), or "patch" (X.Y.Z+1).
  First-time checkins keep their initial version unchanged.

After checkin, the widget is available in the library for search and install.""",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the widget/blueprint directory to submit"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the change - used in changelog (e.g., 'New widget: rate limiter with token bucket algorithm')"
                },
                "differentiation": {
                    "type": "string",
                    "description": "How this differs from similar items (helps with duplicate detection). Required if similar widgets exist."
                },
                "version_bump": {
                    "type": "string",
                    "enum": ["minor", "major", "patch"],
                    "description": "How to bump the version on update. 'minor' (default): X.Y+1.0, 'major': X+1.0.0, 'patch': X.Y.Z+1. Ignored on first checkin."
                }
            },
            "required": ["path", "reason"]
        }
    ),
    Tool(
        name="cartographer_compare",
        description="""Compare installed widget(s) against library versions to check for updates.

RETURNS:
  - status: 'clean' (up to date), 'outdated' (new version available), 'modified' (local changes), 'not_installed'
  - installed_version vs library_version
  - changelog: What changed in newer versions

USE CASES:
  - Check if updates are available for a widget
  - Detect if local code was modified from library version
  - Review changelog before upgrading""",
        inputSchema={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "ID of specific item to compare"
                },
                "all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Compare all installed items at once"
                }
            }
        }
    ),
    Tool(
        name="cartographer_popular",
        description="""List the most installed/popular widgets and blueprints.

Good for discovering proven, battle-tested widgets that the community trusts.
Sorted by install_count descending.""",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of items to return"
                }
            }
        }
    ),
    Tool(
        name="cartographer_uninstall",
        description="""Remove an installed widget from your project.

WARNING: This DELETES the widget directory and all its files.
Only works on widgets inside the cartographer/ directory (safety check).

After uninstall, the widget is removed from the installed index.""",
        inputSchema={
            "type": "object",
            "properties": {
                "widget_id": {
                    "type": "string",
                    "description": "ID of the widget to uninstall and delete"
                }
            },
            "required": ["widget_id"]
        }
    ),
    Tool(
        name="cartographer_rate",
        description="""Add a rating and review to an installed widget.

REQUIREMENTS:
  - Must provide PATH to installed widget (proof of installation)
  - Cannot rate widgets you haven't installed

IMPACT:
  - Review is saved to the library's reviews.json
  - Affects the widget's rating shown in search results
  - Helps other developers choose quality widgets

WHEN TO RATE:
  - After successfully using a widget in your project
  - When you find issues or have suggestions
  - To recommend (or warn about) a widget""",
        inputSchema={
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Path to installed widget directory (e.g., './cartographer/logic-retry-python')"
                },
                "score": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Rating: 1=poor, 2=below average, 3=average, 4=good, 5=excellent"
                },
                "comment": {
                    "type": "string",
                    "description": "Review comment - what worked, what didn't, suggestions"
                },
                "author": {
                    "type": "string",
                    "default": "anonymous",
                    "description": "Your name or identifier for the review"
                }
            },
            "required": ["item", "score", "comment"]
        }
    )
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
        if name == "cartographer_search":
            result = get_carto().search(
                query=arguments["query"],
                domain_filter=arguments.get("domain", "all"),
                language_filter=arguments.get("language"),
                type_filter=arguments.get("type", "all")
            )

        elif name == "cartographer_inspect":
            result = get_carto().inspect(
                widget_id=arguments["widget_id"],
                show_examples=arguments.get("show_examples", False) or arguments.get("show_all", False),
                show_source=arguments.get("show_source", False) or arguments.get("show_all", False),
                show_tests=arguments.get("show_tests", False) or arguments.get("show_all", False)
            )

        elif name == "cartographer_install":
            result = get_carto().install(
                widget_id=arguments["widget_id"],
                target_dir=arguments.get("target", "cartographer"),
                version=arguments.get("version"),
                blueprint=arguments.get("blueprint")
            )

        elif name == "cartographer_validate":
            result = get_carto().validate_item(path=arguments["path"])

        elif name == "cartographer_create":
            result = get_carto().create(
                item_id=arguments["item_id"],
                language=arguments.get("language"),
                name=arguments.get("name"),
                domain=arguments.get("domain", "backend"),
                tags=arguments.get("tags"),
                target_dir=arguments.get("target"),
                item_type=arguments.get("item_type", "widget"),
                composed_of=arguments.get("composed_of"),
                gpu_targets=arguments.get("gpu_targets"),
                widget_type=arguments.get("widget_type")
            )

        elif name == "cartographer_checkin":
            result = get_carto().checkin(
                path=arguments["path"],
                reason=arguments["reason"],
                version_bump=arguments.get("version_bump", "minor")
            )

        elif name == "cartographer_compare":
            if arguments.get("all", False):
                result = get_carto().compare_all_installed()
            else:
                item_id = arguments.get("item_id")
                if item_id:
                    result = get_carto().compare_versions(item_id)
                else:
                    result = {"error": "Provide item_id or set all=true"}

        elif name == "cartographer_popular":
            result = get_carto().list_popular(limit=arguments.get("limit", 10))

        elif name == "cartographer_uninstall":
            result = get_carto().uninstall(widget_id=arguments["widget_id"])

        elif name == "cartographer_rate":
            result = get_carto().add_review(
                installed_path=arguments["item"],
                rating=arguments["score"],
                comment=arguments["comment"],
                author=arguments.get("author", "anonymous")
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
        return JSONResponse({"status": "healthy", "service": "cartographer-mcp"})

    app = Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[
            # Mount the session manager as an ASGI sub-application
            Mount("/mcp", app=session_manager.handle_request),
            Route("/health", health_handler),
        ]
    )

    print(f"🚀 Cartographer MCP Server running at http://{host}:{port}")
    print(f"   MCP endpoint: http://{host}:{port}/mcp")
    print(f"   Health check: http://{host}:{port}/health")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cartographer MCP Server")
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
