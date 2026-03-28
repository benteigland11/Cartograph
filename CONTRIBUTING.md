# Note from the author - Ben Teigland

I am very excited to have you along for this ride! This project was born out of personal frustrations with code quality and portability of AI written code. By trade I am not a CS person, which might be reflected in opinated decisions made about validation engines. I am trained in Electrical Engineering so a systems focus with simple first is my intention. I will be using AI to review submitted PRs, as admittedly I do not know programming well enough for manual review. However, I will not rely on a single pass. This whole project is based on scrutinizing what the AI lets through, and I intend to do that for reviews.

With that said, I do encourage you to use AI to build onto our engine. People who understand the philosophy of this tool are highest valued, if you can write the code yourself then that's an added bonus! You will not be rejected if Claude or some other chatbot is a co-author. However, if you submit a large PR it is more likely to be rejected. A large PR with 90% correct code but 10% causing issues will be rejected. You are better submitting it as chunks so get that 90% in.

# Contributing to Cartograph

The following guide covers the basic mechanics.

## Getting started

```bash
git clone https://github.com/benteigland11/Cartograph.git
cd cartograph
pip install -e .
pytest
```

Run `cartograph doctor` to verify all language engine dependencies are installed if you intend to work with them.

## What to work on

- Check open issues for bugs and feature requests
- New language engines (see `cartograph/languages/` for the pattern) - Please note this will be heavily reviewed. Each langauge took a few days of trial and error with AI coding to start. Validation is the service.
- Search improvements (`cartograph/search/`)

## Writing code

- Run `pytest` before submitting. Tests live in `tests/`.
- No extra dependencies unless absolutely necessary. The core uses only `platformdirs` and `rank-bm25` plus any language files.
- Keep cloud logic in `cloud.py`. Keep auth logic in `auth.py`. The CLI is in `cli.py`.
- If you add a new command, update the setup command to reflect the new command reference.

## Adding a language

Supporting a language means owning its full validation pipeline, not just generating files. See `cartograph/languages/base.py` for the interface and `cartograph/languages/python.py` for a complete implementation.

A language engine must:
- Run tests and report pass/fail
- Measure code coverage (if applicable. General rule, if it is possible to measure it should be measured and sit at 80%)
- Execute example files (if applicable. Many languages, like js, won't have executable example files, but if it can be ran it should be)
- Clean up after itself. No temp files!

If a language engine gets picked up in this repo it will be pushed up to the cloud registry quickly.

## Pull requests

- Keep PRs focused. One feature or fix per PR. Adding support for a new language counts as a single feature if fully put together. We will not accept half written language engines.
- Include a clear description of what changed and why.
- If you're adding a new command, include `--help` output in the PR description.

## Cloud registry

The default registry is hosted at the URL configured in `cartograph/auth.py`. You can point to your own registry by setting `CARTOGRAPH_REGISTRY_URL`. The registry API is documented by the endpoints in `cartograph/cloud.py`. We recommend using the default cloud registry to create a network effect and use a custom one for enterprise systems.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
