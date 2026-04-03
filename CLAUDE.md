
## Cartograph

Cartograph is a widget library manager. Widgets are reusable code modules
with tests, examples, metadata, and declared dependencies. Third-party
packages are fully supported - widgets just can't depend on other widgets.
When installed into a project they live under `cg/<widget_id>/`.

Before writing reusable logic, search the library first. For any Cartograph actions, always use the CLI.

### Widget structure
```
cg/<widget_id>/
  widget.json          metadata, version, dependencies
  src/                 source code
  tests/               test files (80%+ coverage required)
  examples/            example_usage.* (must run), usage_hint.* (optional)
```

widget_id format: `<domain>-<name>-<language>` e.g. `backend-retry-backoff-python`

Do not edit installed widget files directly - local edits are overwritten on
update. Wrap or extend in your own code instead.

### Commands
`<arg>` = required  `[arg]` = optional

All commands run from your project root. Widgets install to `cg/` in the
current directory (or the directory specified by `--target`).

**Find and use widgets**

    cartograph search <query> [--domain ...] [--language ...]
      Search for widgets matching a query.

    cartograph inspect <widget_id> [--source] [--reviews] [--version X]
      View a widget's metadata, source code, or reviews.

    cartograph install <widget_id> [--target .] [--version X]
      Install a widget into your project.

    cartograph uninstall <widget_id> [--target .]
      Remove an installed widget from your project.

    cartograph upgrade <widget_id> [--target .] [--version X]
      Update an installed widget to the latest version.

    cartograph status [widget_id] [--target .]
      Check if an installed widget is outdated or locally modified.

    cartograph rate <widget_id> <score 1-5> [--comment "..."]
      Rate an installed widget (1-5). Ratings affect search ranking.

**Create and publish widgets**

    cartograph create <widget_id> --language <lang> --domain <domain>
      Scaffold a new widget with the correct directory structure.

    cartograph validate [path] [--lib]
      Run tests, check for contamination, and verify widget correctness.

    cartograph checkin [path] --reason "..." [--bump patch|minor|major] [--publish]
      Push an edited widget back to the library. Runs validation if needed.

    cartograph rollback <widget_id> [--version X] [--reason "..."]
      Restore a previous version of a widget from history.

    cartograph delete <widget_id> [--confirm]
      Remove a widget from the library and cloud.

**Cloud registry**

    cartograph cloud publish [widget_id] [path] [--visibility ...] [--governance ...]
      Publish a widget to the cloud registry.

    cartograph cloud unpublish <widget_id> [--confirm]
      Remove a widget from the cloud registry.

    cartograph cloud sync [--dry-run]
      Sync local library with cloud. Higher version wins.

    cartograph cloud proposals [widget_id] [--accept] [--reject] [--reason "..."]
      Review community-submitted changes to your published widgets.

**Library transfer**

    cartograph export [--output file.zip]
      Export the widget library as a zip for backup or transfer.

    cartograph import <file.zip> [--force]
      Import a widget library from a zip. --force overwrites existing files.

**Custom validation rules**

    cartograph rules
      List all active rules files.

    cartograph rules init --language <lang> [--global]
      Create a rules file from a template. Edit it in your editor to add
      checks. Runs automatically during `cartograph validate`.
      Per-project: .cartograph/rules/   Global: <data_dir>/rules/

**Configuration**

    cartograph config [key] [value]
      View or change settings.

    cartograph setup [--agent ...] [--file X] [--print] [--workflow]
      Write Cartograph instructions to your agent's config file.
      Auto-detects agent. Appends, never replaces.

**Library and account**

    cartograph stats
      Show library statistics.

    cartograph doctor
      Check system health - library, languages, cloud connectivity.

    cartograph login [--token X]
    cartograph logout
    cartograph whoami
    cartograph dashboard
