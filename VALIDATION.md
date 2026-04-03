# Validation Matrix

What Cartograph checks for, per language. Every check here was a deliberate decision.

## Pipeline Order

1. Structure (path, widget.json, required fields)
2. Domain/language validation
3. Contamination scan (blocks stop the pipeline, warnings are overridable)
4. Language-specific validation
5. Dependency installation
6. Example execution
7. Tests (with coverage where supported)
8. Custom rules (if configured)
9. Uniqueness check (implementation hash)

## Shared Checks (All Languages)

These are requirements. Validation fails if any are not met.

| Check | Fails if |
|-------|----------|
| Path exists | missing |
| widget.json exists and valid JSON | missing or invalid |
| No [TODO] placeholders in widget.json | present |
| meta.id, meta.name, meta.domain present | missing |
| meta.domain is valid value | invalid |
| tech_stack.language present | missing |
| tech_stack.dependencies present | missing |
| src/, tests/, examples/ exist with files | missing or empty |
| No widget-on-widget dependencies | present |
| Dependencies have version pins | missing version spec |
| Example runs cleanly | exits non-zero |
| Tests pass | any test fails |
| Implementation is unique (hash) | duplicate found |

## Coverage

| Language | Coverage Enforced | Threshold | Tool |
|----------|------------------|-----------|------|
| Python | Yes | 80% | pytest-cov (--cov-fail-under) |
| JavaScript/TypeScript | Yes | 80% | @vitest/coverage-v8 |
| Nim | No | N/A | No stdlib coverage tool exists |

Nim coverage would require compiling via `--debugger:native` and running `gcov`/`lcov` on the generated C code. This produces C-level line coverage, not Nim source-level coverage. Decided it was too unreliable and confusing to impose on widget authors.

## Language-Specific Validation

### Python

| Check | Fails if | Method |
|-------|----------|--------|
| `src/__init__.py` exists | missing | file check |
| No print() in src/ | present | AST (ignores docstrings) |

### JavaScript/TypeScript

| Check | Fails if | Method |
|-------|----------|--------|
| Native JS scanner passes | issues found | js_scanner.js (tokenizer) |

### Nim

| Check | Fails if | Method |
|-------|----------|--------|
| src/ has .nim files | missing | file check |
| nim check passes | errors found | subprocess (semantic) |
| nim c --compileOnly passes | errors found | subprocess (codegen) |
| Native Nim scanner passes | issues found | nim_scanner.nim |
| .nimble file exists | missing | file check |

## Contamination Scanning

Each language has a native scanner written in that language (not regex from Python).
Python uses AST parsing. JS uses a token-based parser. Nim uses line-based scanning with string/comment awareness.

### Fails validation if found (src/ only unless noted)

| Pattern | Python | JS | Nim | Notes |
|---------|--------|----|-----|-------|
| Debug output (print/echo/console.log) | Yes (AST, src/ only) | Yes (src/ block, tests/ warn, examples/ allow) | Yes (src/ block, tests/ warn, examples/ allow) | |
| Process exit (sys.exit/process.exit/quit) | Yes (AST) | Yes | Yes | |
| Sleep/blocking calls | Yes (AST) | Yes | Yes | Tests/examples: warn if > 1s |
| Absolute paths in strings | Yes | Yes | Yes | /home/, /Users/, C:\ |
| Hardcoded credentials | Yes | Yes | Yes | api_key, secret_key, password, etc. In tests: warning |
| Hardcoded IPs | Yes | Yes | Yes | N.N.N.N pattern. In tests: warning |
| eval() | No | Yes | N/A | JS-specific |
| C FFI pragmas ({.importc.}, {.compile.}) | N/A | N/A | Yes | Nim-specific |
| Global mutable state ({.global.}) | N/A | N/A | Yes | Nim-specific |
| when isMainModule | N/A | N/A | Yes | Widgets are libraries |
| OS-specific when defined() | N/A | N/A | Yes | Platform portability |
| Risky stdlib imports | N/A | Yes (fs, child_process, etc.) | Yes (os, osproc, etc.) | Python does not block these |

### Warnings (overridable)

| Pattern | Python | JS | Nim | Notes |
|---------|--------|----|-----|-------|
| Hardcoded URLs | Yes | Yes | Yes | Excludes localhost, example.com, .test |
| Hardcoded values (constants) | Yes (AST) | Yes (config-like names) | Yes | |
| Unlisted imports | Yes (AST) | Yes | Yes | Not in stdlib or deps |
| Environment variable access | Yes | Yes | Yes | os.getenv, process.env, getEnv |
| Old-style stdlib imports | No | No | Yes | `import json` vs `import std/json` |
| Top-level mutable state | No | No | Yes | `var` at module level |
| Credentials in tests | Yes | Yes | Yes | "verify it's fake" |

## Decisions and Known Limitations

**Why no risky import blocking for Python?**
Python's stdlib (os, subprocess, etc.) is commonly used in legitimate widget code. Blocking it would make most widgets invalid. JS and Nim block their equivalents because those ecosystems have different conventions around filesystem access.

**Why Nim has more checks than others?**
Nim's compilation model (compiles to C, links native) means more things can go wrong portably. Platform-specific `when defined()`, C FFI, and global state are Nim-specific concerns.

**Why line-based scanning for Nim instead of AST?**
The line-based scanner uses only stdlib and has no compiler dependencies. If false positives become a problem, AST parsing via `compiler/parser` can be revisited.

**Why tests run twice if users want custom test flags?**
Custom rules can call the test runner again with their preferred flags (testament --megatest, pytest --benchmark, etc.). Tests run once our way (the quality guarantee), once their way (their preferences). This avoids the complexity of flag merging and keeps the base validation clean.
