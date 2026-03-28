# Contributing to Cartograph

Thanks for your interest in contributing. This guide covers the basics.

## Getting started

```bash
git clone https://github.com/your-org/cartograph.git
cd cartograph
pip install -e .
pytest
```

Run `cartograph doctor` to verify all language engine dependencies are installed.

## What to work on

- Check open issues for bugs and feature requests
- FEEDBACK.md has known UX issues reported by real users
- New language engines (see `cartograph/languages/` for the pattern)
- Search improvements (`cartograph/search/`)
- Seed library widgets (`cartograph/seed_library/`)

## Writing code

- Run `pytest` before submitting. Tests live in `tests/`.
- No extra dependencies unless absolutely necessary. The core uses only `platformdirs` and `rank-bm25`.
- Keep cloud logic in `cloud.py`. Keep auth logic in `auth.py`. The CLI is in `cli.py`.
- If you add a new command, update CLAUDE.md's command reference.

## Widget contributions

Widgets go through the same validation pipeline as everything else:

```bash
cartograph create <widget_id> --language python --domain backend
# write your code in src/, tests in tests/, example in examples/
cartograph validate
cartograph checkin --reason "initial version"
```

The validator enforces structure, coverage (80%+), example execution, and contamination scanning. If it doesn't pass, it doesn't go in.

## Adding a language

Supporting a language means owning its full validation pipeline - not just generating files. See `cartograph/languages/base.py` for the interface and `cartograph/languages/python.py` for a complete implementation.

A language engine must:
- Run tests and report pass/fail
- Measure code coverage
- Execute example files
- Clean up after itself

## Pull requests

- Keep PRs focused. One feature or fix per PR.
- Include a clear description of what changed and why.
- If you're adding a new command, include `--help` output in the PR description.

## Cloud registry

The default registry is hosted at the URL configured in `cartograph/auth.py`. You can point to your own registry by setting `CARTOGRAPH_REGISTRY_URL`. The registry API is documented by the endpoints in `cartograph/cloud.py`.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
