# Note from the Author - Ben Teigland

I am very excited to have you along for this ride! This project was born out of personal frustrations with code quality and portability of AI written code. By trade I am not a CS person, which might be reflected in opinionated decisions made about validation engines. I am trained in Electrical Engineering so a systems focus with simple first is my intention. I will be using AI to review submitted PRs, as admittedly I do not know programming well enough for manual review. However, I will not rely on a single pass. This whole project is based on scrutinizing what the AI lets through, and I intend to do that for reviews.

With that said, I do encourage you to use AI to build our engine. People who understand the philosophy of this tool are highest valued, if you can write the code yourself then that's an added bonus! You will not be rejected if Claude or some other chatbot is a co-author. However, if you submit a large PR it is more likely to be rejected. A large PR with 90% correct code but 10% causing issues will be rejected. You are better submitting it as chunks to get that 90% in.

Thank you for your interest in supporting this project!

--- Ben Teigland

# Contributing to Cartograph

## Philosophy

Cartograph is built on a few principles that guide every decision:

**Validation is the product.** The whole value of the library is that everything in it has been fully tested to a consistent standard. If validation can't actually run and verify a widget works, it doesn't go in. This means we move slowly and deliberately when touching the validation pipeline.

**Opinionated by design.** The built-in validation thresholds (80% coverage, test timeouts, contamination rules) are intentionally not user-configurable. If users can lower the bar, "validated" stops meaning anything. The custom rules system lets users add stricter checks on top, but never loosen the base guarantees. If we decide to change these then we must make it clear we are changing our standard for what validated means to us.

**Zero external dependencies.** The core engine uses only the Python standard library. Language-specific tooling (pytest, vitest, nimble) is invoked via subprocess, not imported. This keeps installs clean and avoids dependency conflicts. It is also in response to recent supply chain attacks. This needs to be a trusted tool.

**We enforce rules, we don't write tests.** The validation pipeline runs the widget author's tests with their chosen tools and enforces quality thresholds (80% coverage, passing tests, clean examples). We never inject test configurations, environments, or frameworks. The widget author owns their test setup - we just verify the results meet the bar. This is the same model as a CI system: you bring your tests, we bring the standards.

**Support a language fully or not at all.** Adding a language means owning its entire validation pipeline. Tests, coverage, contamination scanning, example execution, dependency isolation. We don't ship partial support.

## Getting started

```bash
git clone https://github.com/benteigland11/Cartograph.git
cd Cartograph
pip install -e .
pytest
```

The project uses a `src/` layout. Source lives at `src/cartograph/`, CLI entry point is `src/cartograph/cli.py`.

Run `cartograph doctor` to verify all language engine dependencies are installed if you intend to work with them.

## What to work on

- Check open issues for bugs and feature requests
- New language engines (see `src/cartograph/languages/` for the pattern). Please note this will be heavily reviewed. Each language took a few days of trial and error with AI coding to get right. Validation is the service.
- Search improvements (`src/cartograph/search/`)
- Contamination scanner improvements (`src/cartograph/languages/scanners/`)

## Writing code

- Run `pytest` before submitting. Tests live in `tests/`. All 240+ tests must pass.
- No extra dependencies. The core uses only the stdlib.
- Keep cloud logic in `src/cartograph/cloud.py`. Keep auth logic in `src/cartograph/auth.py`. The CLI is in `src/cartograph/cli.py`.
- If you add a new command, update `_SETUP_INSTRUCTIONS` in `cli.py` and the command reference in `CLAUDE.md`.

## Adding a language

Supporting a language means owning its full validation pipeline, not just generating files. See `src/cartograph/languages/base.py` for the interface and `src/cartograph/languages/python.py` for a complete implementation.

All widgets follow the same directory structure regardless of language:

```
cg/<widget_id>/
  widget.json          # metadata, version, dependencies
  src/                 # source code
  tests/               # test files
  examples/
    example_usage.*    # must run successfully
```

If a language requires additional files at the widget root (like `.nimble` for Nim or `package.json` for JS), the engine's `scaffold()` method must create them and `_copy_widget` in `src/cartograph/installer.py` must copy them on install.

**Angular-specific notes:** Angular widgets are library projects (not app projects). The scaffold creates `angular.json`, `karma.conf.js`, `tsconfig.lib.json`, `tsconfig.spec.json`, and `ng-package.json` in addition to the standard files. Test files are named `test_<module>.component.ts` (Jasmine specs). Example validation runs `ng build` (build artifact, not script execution) - document this deviation explicitly. Coverage enforcement is via `karma.conf.js` `check.global` thresholds at 80%, not CLI flags. Chrome or Chromium must be installed for `ng test` to run in CI.

**PHP-specific notes:** PHP widgets use Composer (PSR-4 autoloading, `Cartograph\<ModuleName>` namespace) and PHPUnit 11. Coverage requires Xdebug or PCOV to be installed as a PHP extension - the engine surfaces this in `cartograph doctor` as an optional check. The contamination scanner blocks WordPress globals (`wp_*`, `add_action`, `add_filter`, `$wpdb`, `$wp_query`, etc.) everywhere in src/ to enforce pure PHP utility widgets with no framework coupling. `echo` in src/ is blocked the same way Python's `print()` is. Example files may use `echo` freely. Dependency format in widget.json follows Composer's `vendor/package>=semver` convention; the vendor prefix (e.g. `guzzlehttp`) is used to match against `use` statements' namespace roots.

A language engine must:
- Run tests and report pass/fail
- Measure code coverage (if possible to measure, it should be measured and sit at 80%)
- Execute example files (if the language supports it)
- Provide a native contamination scanner written in the target language (exception: languages with no file I/O capability may use a Python fallback scanner). The scanner must enforce the shared unlisted-import policy: any import that is not stdlib, not a local src/ module, and not declared in widget.json `dependencies` must **block in src/** and **warn in tests/examples**. The fix is trivial (declare the dep or remove the import), so this is not overridable.
- Isolate dependency installation so validation never pollutes the user's environment
- Include a custom rules template in `src/cartograph/rules.py` so users can write validation rules in that language
- Clean up after itself. No temp files, no compiled binaries left behind.
- Update `VALIDATION.md` with the new language's checks, decisions, and any known limitations.

If a language engine gets picked up in this repo it will be pushed up to the cloud registry quickly.

## Pull requests

- Keep PRs focused. One feature or fix per PR. Adding support for a new language counts as a single feature if fully put together. We will not accept half written language engines.
- Include a clear description of what changed and why.
- If you're adding a new command, include `--help` output in the PR description.

## Cloud registry

The default registry is hosted at the URL configured in `src/cartograph/auth.py`. You can point to your own registry by setting `CARTOGRAPH_REGISTRY_URL`. The registry API is documented by the endpoints in `src/cartograph/cloud.py`. We recommend using the default cloud registry to create a network effect and use a custom one for enterprise systems.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
