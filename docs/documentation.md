# Cartograph — Internal Documentation

Developer notes on architecture, non-obvious behaviors, and design decisions.
The README covers user-facing setup. This file is for people working on the codebase.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Widget Structure](#widget-structure)
3. [Engine & Library Loading](#engine--library-loading)
4. [Search](#search)
5. [Validation Pipeline](#validation-pipeline)
6. [Validation Stamp](#validation-stamp)
7. [Checkin Workflow](#checkin-workflow)
8. [Contamination Scanner](#contamination-scanner)
9. [Installer](#installer)
10. [Scaffolding](#scaffolding)
11. [Language Engines](#language-engines)
12. [Library Config & Notes Injection](#library-config--notes-injection)
13. [MCP Server](#mcp-server)
14. [Critical Rules & Invariants](#critical-rules--invariants)

---

## Architecture Overview

```
cartograph/
  engine.py          Core Cartograph class — library loading, search, stats
  server.py          MCP server (stdio + HTTP), tool/prompt/resource definitions
  validator.py       14-point validation pipeline
  checkin.py         Push edits to library: versioning, archive, contamination scan
  installer.py       Install/uninstall/update widgets into projects
  inspector.py       Inspect widgets, list popular, log registrations
  scaffolding/       Widget creation — directory setup, templates per language
  languages/         Language engines: validate_widget, install_deps, run_tests
  search/            Hybrid BM25 + n-gram backend with filters
  library_config.json  General/language/domain notes injected into every widget
```

The flow for the two main agent operations:

**Consuming a widget:** `search → inspect → install → rate`

**Contributing a widget:** `create → (edit files) → validate → checkin`

Everything that enters the library passes the full validation pipeline. There is no bypass.

---

## Widget Structure

```
<widget_id>/
  widget.json
  src/
    __init__.py
    {module}.py
  tests/
    test_{module}.py
  examples/
    example_usage.py
  changelog.json          created on first checkin
  reviews.json            created on first rating
  history/
    {version}/            archived before each update
      src/
      tests/
      examples/
      widget.json
```

### widget.json schema

```json
{
  "meta": {
    "id": "logic-retry-backoff-python",
    "name": "Retry with Backoff",
    "version": "1.1.0",
    "domain": "backend",
    "tags": ["retry", "backoff", "resilience"]
  },
  "description": "Exponential backoff with jitter for retrying failed operations.",
  "tech_stack": {
    "language": "python",
    "dependencies": ["requests>=2.28"]
  },
  "library_notes": {
    "general": "...",
    "language": "...",
    "domain": "..."
  }
}
```

**Constraints enforced by validation:**
- All `[TODO]` placeholders must be removed before checkin
- `meta.domain` must be one of: `backend data ml security infra frontend universal`
- `tech_stack.dependencies` must have version pins (`>=`, `==`, `~=`, etc.)
- `meta.tags` must have 3–5 entries (validator blocks on the `[TODO: add 3-5 tags]` placeholder)

### changelog.json

Prepended on every checkin. Most recent entry is index 0.

```json
[
  {
    "version": "1.1.0",
    "reason": "Fix backoff on connection reset",
    "timestamp": "2025-03-04T12:34:56.123456",
    "override_reason": "only present when override_warnings=True was used"
  }
]
```

---

## Engine & Library Loading

**`cartograph/engine.py` — `Cartograph` class**

The engine is the single source of truth for the widget index. Everything else (server, validator, checkin) receives `carto` as a parameter and reads from `carto.widgets`.

### Library path resolution (in priority order)

1. `WIDGET_LIBRARY_PATH` environment variable
2. `Widget_Library/` adjacent to the repo root (dev mode)
3. Platform user data directory (production; seeded from bundled widgets on first run)

### Loading & caching

`_load_library()` scans the library path for `widget.json` files, skipping `history/` subdirectories. For each widget it loads: metadata, tags, description, dependencies, reviews, test count, line count, and implementation hash.

Loading is expensive (file I/O, hashing), so results are cached in `.cartograph/library_cache.json` keyed by widget ID. Cache entries are invalidated per-widget using three mtimes:

- `manifest_mtime` — widget.json changed
- `src_max_mtime` — any src/ file changed
- `reviews_mtime` — reviews.json changed

### Implementation hash

`_calculate_implementation_hash(path)` — MD5 over the contents of all `src/` files, walked in sorted order. Used in two places:

1. **Uniqueness check at validation** — prevents checking in code identical to an existing widget
2. **Modified detection in widget_status** — tells the user whether their installed copy has drifted from the library

### Language normalization

`_normalize_language()` maps common aliases to canonical names:

| Aliases | Canonical |
|---------|-----------|
| `js`, `ecmascript` | `javascript` |
| `ts` | `typescript` |
| `py`, `python3`, `py3` | `python` |
| `rs` | `rust` |
| `golang` | `go` |
| `c++`, `cxx` | `cpp` |
| `c#` | `csharp` |

All search filters, scaffolding, and validators call through this. Never compare language strings directly.

---

## Search

**`cartograph/search/` — hybrid BM25 + n-gram**

### Index

Built once at startup from `carto.widgets`. Fields indexed per widget: `id`, `name`, `tags`, `description`. Source code is not indexed.

### BM25

`rank_bm25.BM25Okapi` on tokenized, lowercased fields. Field weights are implemented by repetition in the document:

| Field | Weight |
|-------|--------|
| id (dashes stripped) | 4× |
| name | 4× |
| tags | 3× |
| description | 1× |

Synonym expansion via `synonyms.json` if present.

### N-gram

Bigram + trigram sets built per field at index time. Query-time Jaccard similarity (`|intersection| / |union|`) with field weights:

| Field | Weight |
|-------|--------|
| id, name | 3.0 |
| tags | 2.0 |
| description | 1.0 |
| source | 0.3 |

### Hybrid scoring

1. Score both backends independently
2. Min-max normalize each to [0, 1] (ties where all non-zero → 1.0)
3. Combine: `0.40 × bm25_norm + 0.60 × ngram_norm`
4. Apply exact substring boost: +0.30 if a query term appears verbatim in name or id
5. Filter: domain/language filters, minimum score 0.10
6. Sort descending, return top_k (default 15)

Domain filter passes widgets whose domain matches the filter **or** is `universal`.

---

## Validation Pipeline

**`cartograph/validator.py` — `validate_item(carto, path)`**

Runs 14+ checks in order. Fails fast — the first failed check returns an error immediately without running subsequent checks.

| # | Check | Notes |
|---|-------|-------|
| 1 | Path exists | |
| 2 | widget.json exists | |
| 3 | widget.json is valid JSON | |
| 4 | No `[TODO]` placeholders in widget.json | Counts all occurrences |
| 5 | `meta.id`, `meta.name`, `meta.domain` present | |
| 6 | `meta.domain` is a known value | Validates against `VALID_DOMAINS` |
| 7 | `tech_stack.language` present | |
| 8 | `tech_stack.dependencies` present | Empty array `[]` is valid |
| 9 | `src/`, `tests/`, `examples/` exist and are non-empty | |
| 10 | `src/__init__.py` imports cleanly | Subprocess: `python -c "import src"`, 10s timeout |
| 11 | `examples/example_usage.py` exists | |
| 12 | No `[TODO]` in example_usage.py | |
| 13 | `example_usage.py` runs cleanly | Subprocess execution, 15s timeout |
| 14 | Test files exist (`tests/test_*.py`) | |
| 15 | Language-specific static checks pass | Engine's `validate_widget()` |
| 16 | Dependencies install successfully | Engine's `install_deps()` |
| 17 | All tests pass with ≥80% coverage | Engine's `run_tests()` (Python: pytest-cov) |
| 18 | Implementation hash is unique | No existing widget with same src/ MD5 |

On success, a [validation stamp](#validation-stamp) is written to the widget directory.

---

## Validation Stamp

After a successful `validate_item()`, `.validation_stamp.json` is written into the widget directory:

```json
{
  "language": "python",
  "fingerprint": "<sha256>"
}
```

The fingerprint is SHA-256 over every watched file's relative path and content, processed in sorted order for determinism. `checkin` checks this stamp before running the full pipeline — if the stamp is fresh, the expensive validation is skipped entirely.

### What invalidates the stamp

Any content change to a watched file produces a different fingerprint and silently forces full re-validation on the next checkin. Watched files are defined per language engine via `LanguageEngine.watched_patterns(path)`. The base default covers `src/**`, `tests/**`, `examples/**`, and `widget.json`.

Language engines can override `watched_patterns` to add language-specific manifest files (e.g. `Cargo.toml` for Rust, `go.mod` for Go, `package.json` for JS).

### The stamp never enters the library

`.validation_stamp.json` is excluded from:
- The file copy to the library directory
- The history archive written before an update
- Both `shutil.ignore_patterns` calls in `checkin.py`

### Security tradeoff

The stamp is a **performance optimization, not a security boundary**.

Anyone with filesystem write access to the widget directory can forge a stamp by calling `write_stamp()` directly on modified files. This is acceptable because Cartograph is a local, single-user tool — anyone who can forge a stamp also has direct write access to the library files. The checkin pipeline is not a security gate against a malicious local actor.

If Cartograph ever runs in a multi-user or shared-library context, the stamp should be hardened with an HMAC signed by a machine-local secret (stored in e.g. `~/.cartograph/secret`, generated on first run). Not on the roadmap until there is a concrete multi-user deployment.

---

## Checkin Workflow

**`cartograph/checkin.py` — `checkin(carto, path, reason, version_bump, override_warnings, override_reason)`**

1. **Read manifest** — load widget.json, extract `meta.id`
2. **Validate** — skip if stamp is fresh; otherwise run full `validate_item()` pipeline
3. **Version conflict check** — if widget already exists in library, local version must match library version exactly (prevents overwriting a newer version with an older base)
4. **Contamination scan** — see [below](#contamination-scanner)
5. **Version bump** (updates only):
   - `major`: increment major, reset minor + patch
   - `minor` (default): increment minor, reset patch
   - `patch`: increment patch
   - New widgets: version taken from widget.json as-is
6. **Archive** (updates only) — copy current library version to `history/<old_version>/` before overwriting
7. **Restore library_notes** — overwrite `library_notes` in widget.json with canonical values from `library_config.json` (agent edits to this field are always discarded)
8. **Copy to library** — `shutil.copytree` / `copy2`; source working copy is never deleted
9. **Write changelog** — prepend entry to `changelog.json`
10. **Generate diff** (updates only) — unified diff returned in result for agent review
11. **Reload library** — rebuild in-memory index and search backend

### Restoring library_notes

`_restore_library_notes()` is called immediately before the copy step. It reads the canonical notes for the widget's language and domain from `library_config.json` and overwrites whatever is in widget.json. This prevents library-wide standards from drifting even if an agent edited the file during development.

---

## Contamination Scanner

**`checkin.py` — `_scan_contamination(path, widget)`**

Scans `src/` and `tests/` Python files for project-specific content before accepting anything into the library.

### Hard blocks — checkin fails, no override possible

| Pattern | Example |
|---------|---------|
| Absolute paths in src/ | `"/home/alice/project/data"` |
| Credential assignments in src/ | `api_key = "sk-abc123"` |

### Warnings — checkin pauses; agent must pass `override_warnings=True` + `override_reason`

| Pattern | Rationale |
|---------|-----------|
| `os.getenv` / `os.environ` | May be project-specific env assumptions |
| Hardcoded non-example URLs | Non-localhost, non-example.com URLs |
| Hardcoded IPs | `"192.168.1.1"` etc. |
| Unlisted imports in src/ | Import not in stdlib, declared deps, or widget's own modules |
| Possible credentials in tests/ | Tests might have real keys (warns, doesn't block — could be fake fixtures) |

When a warning is overridden, `override_reason` is recorded in `changelog.json` as an audit trail.

---

## Installer

**`cartograph/installer.py`**

### Install

Copies a widget from the library to `<target>/cartograph/<widget_id>/`. Copies: `src/`, `tests/`, `examples/`, `widget.json`, and any language manifest files (`Cargo.toml`, `package.json`, `go.mod`, etc.).

Increments install count in `.cartograph/stats.json` (load → increment → save, to minimize write races).

Safety checks:
- `target_dir` must be an absolute path
- `target_dir` must not be the library itself or the repo root
- If version specified, installs from `history/<version>/` instead of current

### Uninstall

`shutil.rmtree` on the widget directory. Validates that the resolved path is actually inside `target_dir` before deleting (path traversal guard).

### Update

Uninstall then install. Returns both old and new version in the result.

---

## Scaffolding

**`cartograph/scaffolding/`**

`create_widget()` builds a valid widget skeleton that will pass validation once the `[TODO]` stubs are filled in.

**Steps:**
1. Normalize language alias
2. Append language suffix to widget ID if not present (e.g. `my-widget` → `my-widget-python`)
3. Infer display name from widget ID (title-case, strip domain prefix)
4. Create `src/`, `tests/`, `examples/` directories
5. Write `widget.json` with `[TODO]` placeholders for description and tags
6. Write language-specific source, test, and example files from templates

**Tags default:** `["[TODO: add 3-5 tags]"]` — the validator blocks on this string, forcing the agent to fill it in before checkin.

**Domain is required.** There is no silent default — `cartograph_create` will error if domain is omitted.

Templates live in `cartograph/scaffolding/templates.py`. Currently Python only. Each new language needs a corresponding template function registered there.

---

## Language Engines

**`cartograph/languages/`**

Each engine implements three methods defined in `LanguageEngine` (base class):

```python
def validate_widget(path, dependencies) -> dict:
    # Static checks on source structure before tests run
    # Returns {"passed": True} or {"passed": False, "error": str}

def install_deps(path, dependencies) -> None:
    # Install packages needed to run tests. Best-effort, never raises.

def run_tests(path) -> dict:
    # Execute the test suite and enforce coverage
    # Returns {"passed": True} or {"passed": False, "error": str}

def watched_patterns(path) -> list[str]:
    # Glob patterns for validation stamp fingerprinting
    # Override to add language-specific manifest files
```

Engines are registered in `languages/registry.py`. `get_engine(language)` returns the engine instance or `None` for unknown languages.

### Python engine

**Static checks (`validate_widget`):**
- `src/__init__.py` must exist
- No `print()` calls in `src/` — detected with AST walking (ignores docstrings and comments)
- All dependencies must have a version pin

**Test execution:** `pytest tests/ --cov=src --cov-fail-under=80` — 80% coverage required.

**Tests import style:** `sys.path` is set to the widget root; tests import as `from src.module import Thing`. This means `src/__init__.py` gets coverage.

### Adding a new language

1. Subclass `LanguageEngine` in a new file under `languages/`
2. Implement `validate_widget`, `install_deps`, `run_tests`
3. Optionally override `watched_patterns` to add manifest files
4. Register in `languages/registry.py`
5. Add a template in `cartograph/scaffolding/templates.py`

Supporting a language means owning the full validation pipeline — scaffolding, static checks, dep install, test running, coverage enforcement. Stub engines that just return "not supported" exist for JS, Rust, Go, C++, C#, Java but are not yet real implementations.

### ML domain constraint

ML widgets must be fully validatable without torch / tensorflow / jax. The validation environment has no GPU guarantee and these packages are large installs. Allowed: numpy, scikit-learn, plain Python math, and API-based inference wrappers (HTTP calls to OpenAI, Anthropic, HuggingFace, etc.). Framework-dependent code cannot be validated and will not be accepted into the library.

---

## Library Config & Notes Injection

**`cartograph/library_config.json`**

Holds three layers of notes injected into every widget's `library_notes` field:

- `general_notes` — library-wide standards (single responsibility, no global state, etc.)
- `language_notes` — per-language rules (e.g. Python: use pytest, type hints, no unittest)
- `domain_notes` — per-domain rules (e.g. frontend: expose all appearance values as CSS custom properties; ml: no framework-dependent code)

These notes are injected at widget creation time by the scaffolding and **forcibly restored on every checkin** by `_restore_library_notes()`. Agents cannot permanently edit them — any changes made during development are silently overwritten when the widget enters the library.

To update library-wide standards, edit `library_config.json`. The change propagates to all future checkins and all newly created widgets.

---

## MCP Server

**`cartograph/server.py`**

### Tools

| Tool | Purpose |
|------|---------|
| `cartograph_search` | Hybrid search with domain/language filters |
| `cartograph_inspect` | Widget metadata, examples, reviews, optional source |
| `cartograph_install` | Copy widget to `<target>/cartograph/<id>/` |
| `cartograph_update` | Uninstall + reinstall (with optional version pin) |
| `cartograph_uninstall` | Remove installed widget |
| `cartograph_status` | Check if installed widget is outdated or locally modified |
| `cartograph_rate` | Add review (score 1–5, optional comment) |
| `cartograph_create` | Scaffold new widget |
| `cartograph_validate` | Run 14-point validation pipeline |
| `cartograph_checkin` | Submit widget to library |
| `cartograph_setup` | Return per-mode instruction text for project instruction files |

### Prompts

Three multi-step workflow prompts: `checkin-widget`, `install-widget`, `maintain-widgets`.

### Resources

Per-agent instruction files served at `cartograph://instructions/{claude,codex,gemini}`.

### Transport

**Stdio** (default): Async MCP SDK, subprocess communication. This is how Claude Code, Codex, and Gemini CLI connect.

**HTTP**: Starlette + uvicorn, stateless session manager, endpoint at `/mcp`, health check at `/health`. Exists for future cloud/remote use; not currently deployed.

---

## Critical Rules & Invariants

These are constraints that the codebase enforces and that new code must respect.

**Validation is always the gate.** Nothing enters the library without passing `validate_item()`. The validation stamp provides a fast path but does not bypass the constraint — it only skips re-running checks that have already passed and whose inputs haven't changed.

**Library_notes are always canonical.** Never trust `library_notes` from a widget.json in a working copy. They are overwritten on checkin. To change what notes say, edit `library_config.json`.

**Language strings must be normalized.** Always use `carto._normalize_language()` before comparing language values. Raw aliases are accepted as input but must be resolved to canonical form before any logic.

**The source working copy is never deleted.** `checkin` copies to the library; it never moves. The installed copy is left intact after a successful checkin.

**History is append-only.** Old versions are archived to `history/<version>/` before being overwritten. Never delete history entries.

**Path safety in uninstall.** The resolved uninstall path must be verified to be inside `target_dir` before `rmtree`. This is already implemented — don't remove it.

**No silent domain default.** `cartograph_create` requires `domain` explicitly. There is no fallback value.

**Example must be standalone.** `examples/example_usage.py` must run to completion with no user input, no network calls, and no external state. The validator executes it as a subprocess.
