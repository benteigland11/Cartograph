# cartograph-cli

The Cartograph CLI: widget library manager with a per-language validation
pipeline (contamination -> validate -> checkin). Philosophy and the
non-negotiables (validation is the product, stdlib-only, opinions not
configurable) live in CONTRIBUTING.md. Read it before touching validation.

Sources of truth (don't restate them here, they drift):
- Command surface: `cartograph --help` / `cartograph <command> --help`
- Domains: `src/cartograph/library_config.json`
- Engines: `src/cartograph/languages/`

## Layout

    src/cartograph/            CLI + engine (cli.py, engine.py, validator.py, ...)
    src/cartograph/languages/  one module per language engine
    cg/                        widgets this repo dogfoods (ships in the package)
    tests/                     pytest suite

## Dev loop

- `pip install -e .` then run the CLI from this checkout.
- In a git worktree the editable install still points at the main checkout.
  Run tests with `PYTHONPATH=src python -m pytest ...` or you test the wrong code.
- Targeted tests on small changes; the full `pytest` suite before a PR is ready.
- Never add a runtime dependency without a deliberate decision. The CLI is stdlib-only.
- Dogfood: reusable logic becomes a widget under `cg/` first, and the CLI
  imports it. Plan it with the cg-plan flow (search `cg/` + registry first).

## Invariants (each has a guard or a past incident behind it)

- **Validation opinions are fixed.** No knobs for coverage threshold, test
  timeout, or contamination rules. Custom rules add checks on top; they never
  loosen the base. Users wanting extra test flags call their runner again from
  their rules file.
- **Engine bumps are not retroactive.** New checks (warnings or blocks) apply
  when an owner next runs `checkin` / `cloud publish`. Never mass-invalidate,
  hide, or pressure-migrate old stamps. `has_valid_stamp()` ignores
  engine_version on purpose; `is_stamp_valid()` requires it.
- **Pre-v1:** breaking changes to the validation pipeline are allowed until
  v1.0; `test_contamination.py` is the source of truth for the standard.
- **TLS:** every `urlopen` in `src/cartograph` passes
  `context=registry_ssl_context()` (`net_tls.py`). Registry traffic goes through
  the `infra-urllib-client-python` widget. `tests/test_tls_context_guard.py`
  fails the build otherwise.
- **UTF-8:** every text-mode `open()`, `read_text()`, `write_text()` passes
  `encoding="utf-8"`. Windows CI is the only place this breaks.
- **Bundled widgets import through the `cg.` namespace**
  (`from cg.<widget_pkg>.src.<mod> import ...`). Never `sys.path` insert plus
  `from src...`: engines silently vanish from wheels (v0.7.5 incident).
- **Slugs become identifiers.** `validate_name_identifier()` rejects illegal
  identifiers (leading digit, bad chars) loudly with a suggested reorder; do
  not silently mangle.
- **One canonical library:** `WIDGET_LIBRARY_PATH` env, else the platform user
  data dir. No repo-sibling `Widget_Library`. Never hand-edit library files.
- **Library writes are safe:** mutating commands go through `safefs.py`
  (`library_lock`, `staged_dir`/`atomic_swap_dir`, `safe_extractall`). Sleep and
  poll loops live in glue, never in widget `src/` (the validator blocks `sleep()`).
- **JSON scope:** commands in the MCP surface (install, uninstall, upgrade,
  status, search, inspect, stats, create, validate, checkin, rollback, rate,
  ledger) print pure JSON and exit non-zero on error. Human commands (login,
  doctor, config, setup, rules, cloud publish/sync/proposals, ...) may print prose.
- **Search contract:** separate `local` and `registry` pools, registry results
  in received order, bounded rows, per-pool `omitted` counts. A `prior` pool
  from the local usage ledger may be listed first. Rows in that pool are
  chosen by the same hybrid scorer as local search. It does not reorder
  either pool and does not spend the `top_k` budget. Pagination for search
  was rejected; better queries beat page 7.
- **Blueprints are not public.** The public registry refuses blueprint
  publishes (403); `publish_blueprint` preflights `/v1/registry/info`. Org
  registries opt in.
- **`setup` writes only inside the project**, never to `~/.claude`,
  `~/.codex`, or other agent globals. Other commands follow that rule, except
  files that already live in the Cartograph data directory (`config.toml`,
  `stats.json`) and the usage ledger.
- **Usage ledger:** machine-local file `<data-dir>/.state/usage-ledger.jsonl`.
  It records install, upgrade, uninstall, and `ledger note` (widget id,
  version, project path, git origin when one exists, time, and purpose).
  Search scores those rows with the same hybrid scorer as local search,
  over the widget id, purpose, project directory name, and git origin, and
  adds a `prior` pool plus `prior_use` on matching rows without reordering
  local or registry results. Ledger contents are never sent to a registry.
  `cartograph config usage-ledger false` turns recording and search reads
  off. `cartograph ledger forget --all` deletes the rows.
- **Nim widgets are pure Nim.** `{.importc.}` / `{.compile.}` stay banned; point
  users to stdlib composition or a nimble package.
- **Heavy ML frameworks** are allowed only if pre-installed; never auto-install,
  never mock torch and call it validated.
- When testing a cloud header or response contract, verify through the CLI,
  not curl.

## Pre-flight (engine / release PRs)

1. Full local `pytest` green, including the language's create /
   contamination / blueprint suites.
2. Real-widget stress: at least one widget through the actual CLI
   (`cartograph create` -> `validate`), not engine methods.
3. Remote validation nodes (Mac / Windows) run from Ben's workstation. If you
   cannot run them, say so in the PR; Ben runs them before merge.
4. PR CI green on all 9 matrix combos (plus wheel-verify) before merging.

## Releasing

Master push -> test.yml -> auto-tag -> publish.yml (PyPI, fresh-install
check, GitHub release). Auto-tag only fires when `pyproject.toml`'s version
has no tag yet, so a release needs a version bump; a merged PR alone ships
nothing. Merging a bumped PR is a release: only Ben merges. After merge,
verify the version on origin/master, the `vX.Y.Z` tag (`git fetch --tags`),
and PyPI.

## Repo rules

- Branch off `origin/master`, open a PR, never push to master.
- No `git reset --hard` / `git clean -f` / `git checkout -- <file>` over work
  that isn't yours; `git stash push -u` first.
- No em dashes in code, comments, or docs.
- Keep private infra details (GCP projects, customers, secrets) out of this
  public repo.
