
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
`<arg>` = required  `[arg]` = optional  defaults shown where relevant

**Find and use widgets**

    cartograph search <query>
        [--domain backend|data|ml|security|infra|frontend|universal]
        [--language python|javascript|typescript|nim]

    cartograph inspect <widget_id>
        [--source]         include source files
        [--reviews]        include review comments
        [--all-versions]   list full version history
        [--version X]      inspect a specific version

    cartograph install <widget_id> [--target .] [--version X]
    cartograph uninstall <widget_id> [--target .]
    cartograph upgrade <widget_id> [--target .] [--version X]
    cartograph status [widget_id] [--target .]
    cartograph rate <widget_id> <score 1-5> [--comment "..."] [--target .]

**Create and publish widgets**

    cartograph create <widget_id>
        --language python|javascript|typescript|nim    REQUIRED
        --domain backend|data|ml|security|infra|frontend|universal  REQUIRED
        [--name "Display Name"] [--target .]

    cartograph validate [path] [--lib]   path defaults to .
    cartograph checkin [path]            path defaults to .
        --reason "what changed and why"  REQUIRED
        [--bump patch|minor|major]       defaults to minor
        [--publish]                      also publish to cloud

    cartograph rollback <widget_id> [--version X] [--reason "..."]
    cartograph delete <widget_id> [--confirm]       also unpublishes from cloud

**Cloud registry**

    cartograph cloud publish [widget_id] [path]
        [--lib]                          publish from library by ID
        [--visibility public|private]    override default visibility
        [--governance open|protected]    override default governance
    cartograph cloud unpublish <widget_id> [--confirm]
    cartograph cloud settings <@handle/widget_id>
        [--governance open|protected]    change governance model
    cartograph cloud sync [--dry-run]    sync library with cloud (higher version wins)
    cartograph cloud proposals [widget_id] [proposal_id]
        [--accept] [--reject] [--reason "..."]

**Configuration**

    cartograph config                      show all settings
    cartograph config <key>                get a setting
    cartograph config <key> <value>        set a setting

    Keys: auto-publish, visibility, governance

**Library and account**

    cartograph stats
    cartograph doctor
    cartograph login [--token X]
    cartograph logout
    cartograph whoami
    cartograph dashboard
