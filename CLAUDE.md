
## Cartograph

Cartograph is a widget library manager. Widgets are reusable, self-contained
code modules with tests, examples, and metadata. When installed into a project
they live under `cartograph/<widget_id>/`.

Before writing reusable, self-contained logic, search the library first.

### Widget structure
```
cartograph/<widget_id>/
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
    cartograph update <widget_id> [--target .] [--version X]
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

    cartograph push [widget_id] [path]
        [--lib]                          push from library by ID
        [--visibility public|private]    defaults to public

    cartograph delete <widget_id> [--confirm]

**Library and account**

    cartograph stats
    cartograph doctor
    cartograph login [--token X]
    cartograph logout
    cartograph whoami
    cartograph dashboard
