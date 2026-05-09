
## Cartograph

Widget library manager. Widgets are reusable code modules with tests,
examples, and metadata. Installed widgets live under `cg/<widget_id>/`.

widget_id format: `<domain>-<name>-<language>` (e.g. `backend-retry-backoff-python`)

When using `cartograph create`, only provide the name. The `--domain` and
`--language` flags are prepended and appended automatically.
Example: `cartograph create retry-backoff --domain backend --language python`
creates `backend-retry-backoff-python`.

### Domains

    backend    server-side logic, APIs, networking
    frontend   UI components, browser utilities
    data       parsing, transformation, pipelines
    ml         machine learning utilities (must be framework-free)
    security   auth, encryption, scanning
    infra      CLI tools, file ops, system utilities
    modeling   3D geometry, CAD, parametric design (OpenSCAD)
    rtl        register-transfer level hardware design (SystemVerilog)
    universal  language-agnostic, cross-domain

### Commands

All commands run from your project root. Widgets install to `cg/` in the
current directory (or the directory specified by `--target`).

**Find and use widgets**

    search <query> [--domain ...] [--language ...]
      Search for widgets matching a query.

    inspect <widget_id> [--source] [--reviews] [--version X]
      View a widget's metadata, source code, or reviews.

    install <widget_id> [--target .] [--version X]
      Install a widget into your project.

    uninstall <widget_id> [--target .]
      Remove an installed widget from your project.

    upgrade <widget_id> [--target .] [--version X]
      Update an installed widget to the latest version.

    status [widget_id] [--target .] [--page N --size N | --all]
      Check if an installed widget is outdated or locally modified.
      Without widget_id: paginated listing of all installed widgets.
      Default page size 20. Use --all for every widget, or --page/--size
      to step through. Response includes pagination.next_command /
      prev_command strings the agent can run verbatim.

    rate <widget_id> <score 1-5> [--comment "..."]
      Rate an installed widget (1-5). Ratings affect search ranking.

**Create and publish widgets**

    create <widget_id> --language <lang> --domain <domain>
      Scaffold a new widget with the correct directory structure.

    validate [path] [--lib]
      Run tests, check for contamination, and verify widget correctness.

    checkin [path] --reason "..." [--bump patch|minor|major] [--publish]
      Push an edited widget back to the library. Runs validation if needed.
      Version is managed by Cartograph - do NOT hand-edit the version
      field in widget.json. Use --bump to increment.

    rollback <widget_id> [--version X] [--reason "..."]
      Restore a previous version of a widget from history.

    delete <widget_id> [--confirm]
      Remove a widget from the library and cloud.

**Cloud registry**

    cloud publish [id] [path] [--visibility ...] [--governance ...]
      Publish a widget or blueprint to the cloud registry. Dispatches by
      manifest type: blueprint.json -> blueprint flow, widget.json ->
      widget flow. Versions are immutable - fix and bump.

    cloud unpublish <widget_id> [--confirm]
      Remove a widget from the cloud registry.

    cloud adopt <local-id> <@owner/prefix-widget-id>
      Link a local widget to its cloud counterpart by verifying source identity.
      Writes .cartograph_source sidecar so future checkin --publish routes correctly.

    cloud sync [--dry-run]
      Sync local library with cloud. Higher version wins.

    cloud proposals [widget_id] [--accept] [--reject] [--reason "..."]
      Review community-submitted changes to your published widgets.

**Custom validation rules**

    rules
      List all active rules files.

    rules init --language <lang> [--global]
      Create a rules file from a template. Edit it in your editor to add
      checks. Runs automatically during `cartograph validate`.
      Per-project: .cartograph/rules/   Global: <data_dir>/rules/

    rules reset --language <lang> [--global]
      Restore a rules file to its default template.

**Architect (project-level planning)**

    architect init [--path X] [--force]
      Scaffold a starter architect.py at the project root. Architect is
      a project-local Python file describing components and relationships
      (cross-domain: software, modeling, rtl, physical). The agent reads
      it for app-level planning context before reaching for widgets.

    architect validate [--path X]
      Structural checks only: unique component ids, edge/parent ref
      integrity, parent cycles, schema_version, known domains. The
      vibes layer (kind/description/what) is intentionally not checked.

    architect render [--path X] [--output X | --stdout] [--direction TD|TB|LR|BT|RL] [--force]
      Render architect.py as a Mermaid flowchart. Defaults to writing
      architect.mmd next to the source so it commits cleanly and renders
      in GitHub. Refuses to render an invalid architecture unless --force.

    architect link <component_id> <widget_dir> [--path X]
      Link an installed widget to a Component slot. Multiple widgets
      may compose one slot (router + validator + logger as one
      service). Refuses if the widget is not installed under cg/, or
      if it is already linked.

    architect link <component_id> <widget_dir> --clear [--path X]
      Unlink a specific widget from a Component slot.

    architect link <component_id> --clear [--path X]
      Unlink ALL widgets from a Component slot. Edits architect.py via
      AST surgery; comments outside the target Component block are
      preserved.

**Configuration**

    config [key] [value]
      View or change settings.

    registry [add <url> | remove <prefix>]
      Manage additional registries. Prefix is fetched from /info automatically.

    setup [--agent ...] [--file X] [--print] [--workflow]
      Write Cartograph instructions to your agent's config file.
      Auto-detects agent. Appends, never replaces.

    doctor
      Check system health - library, languages, cloud connectivity.

    stats
      Show library statistics.


### Workflow

Think in terms of widgets. Need to add capability, search for a widget.

If you are adding a feature always consider whether it can be added into an existing widget. If not, consider if it could be added as a new widget.
Only project specific wiring should not be made into widgets.

1. Plan what components you need before building
2. Decide whether new implementation can just be an improvement on currently used widgets. Read the widgets before deciding.
3. Search the library before writing new logic
4. Install widgets, then write glue code to connect them. Don't edit widget source directly for this step.
5. If you do edit a widget, only do so if you intend to check it back in as an improvement for the general logic of the widget.
6. Validate before checking in, check in before publishing

Definition of reusable code: Any code that would be written for another project. A lot of code may look "project specific" but if you peel back the logic you will realize it can be used across many projects. These are the widgets that need to be extracted, or made.
