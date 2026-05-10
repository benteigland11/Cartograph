"""Cartograph architecture map.

Cartograph is a code-registry tool with an open-source CLI/engine and a
private cloud registry. This file is the project-level structural map:
who talks to whom, what's a widget vs glue, what still needs writing.

Two repos, one product:
  - cartograph-cli (this repo): the engine, CLI, MCP server, agent
    skills. Open source. Zero external runtime deps.
  - cartograph-cloud (separate private repo): GCP/Cloud Run service
    backed by Firestore + GCS, hosting cartograph.tools.

Modeled from the cli's perspective. Cloud components appear as
deliberate boxes, not externals - they're part of the product. Real
externals are the developer, the LLM agent, and the GCP services we
deploy onto.
"""

from cartograph.architect.schema import Architecture, Component, Edge


architecture = Architecture(
    schema_version="0.1",
    goal=(
        "A widget registry and CLI that lets developers and agents "
        "extract reusable code into versioned, validated, installable "
        "modules - so reusable work isn't lost between projects."
    ),
    components=[
        # --- Externals (no parent, top-level) -----------------------
        Component(
            id="developer",
            kind="external",
            description="The human running cartograph from a terminal.",
        ),
        Component(
            id="agent",
            kind="external",
            description=(
                "LLM (Claude, primarily) using cartograph through "
                "the MCP surface. The agent is a first-class consumer."
            ),
        ),
        Component(
            id="gcp_services",
            kind="external",
            description=(
                "Cloud Run, Firestore, GCS. Cartograph rents these "
                "rather than self-hosting."
            ),
        ),

        # --- cartograph-cli (this repo) -----------------------------
        Component(
            id="cli_engine",
            kind="application",
            description=(
                "The cartograph-cli repository as a whole. Open "
                "source, zero runtime deps. Owns all reusable logic."
            ),
        ),
        Component(
            id='cli_surface',
            kind='entrypoint',
            domains=['infra'],
            parent='cli_engine',
            description='argparse command registration, output formatting, the user-facing CLI verbs. Mostly wiring around the subsystems below; the agent-cli widget provides the framework shape.',
            widgets=[
                'infra_agent_cli_python',
                'infra_command_catalog_python',
                'infra_http_endpoint_registry_python',
            ],
        ),
        Component(id='registry', kind='subsystem', domains=['backend'], parent='cli_engine', description='Local widget library + cloud routing. Search, install, upgrade, status, paginated listings. Multi-registry prefix routing (local/cg-/myorg-).', widgets=['infra_prefix_router_python', 'universal_list_paginator_python']),
        Component(id='engine_dispatcher', kind='subsystem', domains=['infra'], parent='cli_engine', description='Picks the right language engine per widget. Each engine handles validation, contamination scanning, scaffolding for its language.', widgets=['infra_binary_resolver_python']),
        Component(id='python_engine', kind='engine', domains=['backend', 'infra'], parent='engine_dispatcher', description='Representative of the language engine family (python, nim, js, openscad, php, sv, terraform, angular). AST validation, contamination scan, scaffold.', widgets=['universal_block_walker_python']),
        Component(
            id="contamination_orchestrator",
            kind="pipeline",
            domains=["security"],
            parent="cli_engine",
            description=(
                "Three-stage pipeline orchestrator: contamination "
                "-> validate -> checkin. Per-language scanning via "
                "engine.scan_contamination()."
            ),
        ),
        Component(id='validator_pipeline', kind='pipeline', domains=['infra'], parent='cli_engine', description="Drives validation, stamping, and checkin. Refuses to ship widgets that can't be fully validated.", widgets=['infra_file_stamp_python', 'infra_directory_tarball_python', 'infra_version_bump_policy_python']),
        Component(
            id="mcp_server",
            kind="service",
            domains=["backend", "glue"],
            parent="cli_engine",
            description=(
                "MCP daily-driver surface for the agent. Exposes "
                "registry_widget, installed_widget, widget_status, "
                "create_widget, validate_widget, checkin_widget."
            ),
        ),
        Component(
            id="architect_feature",
            kind="subsystem",
            domains=["backend", "infra"],
            parent="cli_engine",
            description=(
                "Project-local architect.py for app-level planning. "
                "init/validate/render/link verbs. The file you're "
                "currently reading is its dogfood."
            ),
            widgets=[
                "cg_universal_graph_cycles_python",
                "cg_universal_python_module_loader_python",
                "cg_universal_mermaid_graph_renderer_python",
            ],
        ),
        Component(
            id='blueprint_feature',
            kind='subsystem',
            domains=['backend'],
            parent='cli_engine',
            description='Pinned widget bundles for repeatable feature installs. Local + org-only since Day 10 ban; never on the public registry.',
            widgets=['infra_directory_tarball_python'],
        ),
        Component(id='cloud_client', kind='client', domains=['backend'], parent='cli_engine', description='HTTPS bridge from cli to the cloud registry. Stdlib urllib only. Auth via stored token.', widgets=['infra_urllib_client_python']),
        Component(
            id="agent_skills",
            kind="content",
            domains=["frontend", "glue"],
            parent="cli_engine",
            description=(
                "Markdown skills shipped to agents via the plugin "
                "marketplace: cg-plan, validate-and-fix, etc. Read "
                "by the agent at runtime, not executed."
            ),
        ),
        Component(
            id="local_state",
            kind="datastore",
            domains=["data"],
            parent="cli_engine",
            description=(
                "~/.local/share/cartograph/ - widget library, "
                "config, auth tokens, history, ratings."
            ),
        ),

        # --- cartograph-cloud (separate repo) -----------------------
        Component(
            id="cloud_service",
            kind="deployment",
            description=(
                "The cartograph-cloud repository. GCP-hosted, "
                "private. Wiring around stdlib + GCP SDKs only - "
                "all reusable logic lives in cli, not here."
            ),
        ),
        Component(
            id="cloud_api",
            kind="service",
            domains=["backend", "glue"],
            parent="cloud_service",
            description=(
                "Cloud Run HTTPS surface. Serves /search, /install, "
                "/publish, /widget/<id>, /info, blog endpoints. "
                "Thin handlers, all logic delegates back to widgets."
            ),
        ),
        Component(
            id="governance",
            kind="policy",
            domains=["security"],
            parent="cloud_service",
            description=(
                "Open vs protected modes. Proposal system for "
                "community contributions to protected widgets."
            ),
        ),
        Component(
            id="safeguard_engine",
            kind="policy",
            domains=["security"],
            parent="cloud_service",
            description=(
                "Publish-time scanning - rejects widgets that fail "
                "safety bars (secrets, contamination, license)."
            ),
        ),
        Component(
            id="registry_db",
            kind="datastore",
            domains=["data"],
            parent="cloud_service",
            description=(
                "Firestore-backed widget metadata: ids, versions, "
                "ratings, owners, governance state."
            ),
        ),
        Component(
            id="widget_blob_storage",
            kind="datastore",
            domains=["data"],
            parent="cloud_service",
            description=(
                "GCS bucket holding widget tarballs (the bytes "
                "metadata in registry_db points at)."
            ),
        ),
        Component(
            id="blog_subsystem",
            kind="feature",
            domains=["backend", "frontend"],
            parent="cloud_service",
            description=(
                "Markdown blog: ADMIN_SECRET-authed write, public "
                "read. Shares the cloud_api process."
            ),
        ),

        # --- cartograph.tools site ----------------------------------
        Component(
            id="tools_site",
            kind="frontend",
            domains=["frontend"],
            description=(
                "cartograph.tools - landing page + blog. Statically "
                "shaped, served by cloud_api on the same Cloud Run "
                "service."
            ),
        ),
    ],
    edges=[
        # User-facing entry
        Edge(source="developer", target="cli_surface", kind="invokes",
             what="terminal commands"),
        Edge(source="agent", target="mcp_server", kind="calls",
             what="MCP JSON-RPC"),
        Edge(source="agent", target="agent_skills", kind="reads",
             what="markdown context"),
        Edge(source="developer", target="tools_site", kind="visits",
             what="HTTPS"),

        # CLI internal composition (cli_surface coordinates)
        Edge(source="cli_surface", target="registry", kind="delegates_to"),
        Edge(source="cli_surface", target="validator_pipeline",
             kind="delegates_to"),
        Edge(source="cli_surface", target="architect_feature",
             kind="delegates_to"),
        Edge(source="cli_surface", target="blueprint_feature",
             kind="delegates_to"),
        Edge(source="cli_surface", target="cloud_client",
             kind="delegates_to"),
        Edge(source="mcp_server", target="cli_surface", kind="reuses",
             what="shared command handlers"),

        # Validator pipeline composition
        Edge(source="validator_pipeline", target="contamination_orchestrator",
             kind="runs", what="stage 1"),
        Edge(source="validator_pipeline", target="engine_dispatcher",
             kind="runs", what="stage 2"),
        Edge(source="contamination_orchestrator", target="engine_dispatcher",
             kind="calls", what="scan_contamination per language"),

        # Registry needs cloud
        Edge(source="registry", target="cloud_client", kind="uses",
             what="cloud lookups"),
        Edge(source="registry", target="local_state", kind="reads_writes"),
        Edge(source="cloud_client", target="cloud_api", kind="calls",
             what="HTTPS"),

        # Cloud internals
        Edge(source="cloud_api", target="governance", kind="enforces"),
        Edge(source="cloud_api", target="safeguard_engine",
             kind="runs", what="at publish time"),
        Edge(source="cloud_api", target="registry_db", kind="reads_writes"),
        Edge(source="cloud_api", target="widget_blob_storage",
             kind="reads_writes"),
        Edge(source="cloud_api", target="blog_subsystem", kind="hosts"),
        Edge(source="tools_site", target="cloud_api", kind="served_by"),

        # Cloud rents GCP
        Edge(source="cloud_service", target="gcp_services", kind="hosted_on"),
    ],
    notes=(
        "Constraints worth remembering when planning changes:\n"
        "- Zero runtime deps in cli_engine (stdlib only). New deps "
        "  require explicit sign-off.\n"
        "- All reusable logic lives in cli_engine, not cloud_service. "
        "  cloud_service is wiring; never duplicate logic into it.\n"
        "- Pre-v1, breaking changes are allowed in cli_engine - bump "
        "  versions, no backwards-compat shims.\n"
        "- mcp_server reuses cli_surface handlers verbatim - if a CLI "
        "  command becomes available, it usually flows to MCP for free."
    ),
)
