## cartograph-cli

The Cartograph CLI: widget library manager with a per-language validation
pipeline (contamination -> validate -> checkin). Philosophy and the
non-negotiables (validation is the product, stdlib-only, opinions not
configurable) live in CONTRIBUTING.md. Read it before touching validation.

Sources of truth (don't restate them here, they drift):
- Command surface: `cartograph --help` / `cartograph <command> --help`
- Domains: `src/cartograph/library_config.json`
- Engines: `src/cartograph/languages/`

### Layout

    src/cartograph/          CLI + engine (cli.py, engine.py, validator.py, ...)
    src/cartograph/languages/  one module per language engine
    cg/                      widgets this repo dogfoods (ships in the package)
    tests/                   pytest suite

### Dev loop

- `pip install -e .` - the daily-driver CLI tracks whatever this checkout has.
- In a git worktree, the editable install still points at the main checkout.
  Run tests with `PYTHONPATH=src python -m pytest ...` or you test the wrong code.
- Run targeted tests on small changes; the full `pytest` suite before merge.
- Never add a runtime dependency without a deliberate decision.

### Pre-flight (engine / release PRs)

1. Full local `pytest` green, including the language's create /
   contamination / blueprint suites.
2. Real-widget stress: at least one widget through the actual CLI
   (`cartograph create` -> `validate`), not engine methods.
3. If remote validation nodes are configured on this machine (the
   workspace's `scripts/remote-stress-*`, outside this repo), run them and
   require PASS.
4. PR CI green on all 9 matrix combos before merging.

### Releasing

Master push -> test.yml -> auto-tag -> publish.yml. Auto-tag only fires
when `pyproject.toml`'s version has no tag yet, so a release needs a
version bump; a merged PR alone ships nothing. After merge, verify the
version on origin/master, the `vX.Y.Z` tag, and PyPI.
