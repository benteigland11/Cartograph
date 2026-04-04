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
| OpenSCAD | No | N/A | Render passes = validation passes |

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

| Pattern | Python | JS | Nim | OpenSCAD | Notes |
|---------|--------|----|-----|----------|-------|
| Debug output (print/echo/console.log) | Yes (AST, src/ only) | Yes (src/ block, tests/ warn, examples/ allow) | Yes (src/ block, tests/ warn, examples/ allow) | Yes (echo(), src/ only) | |
| Process exit (sys.exit/process.exit/quit) | Yes (AST) | Yes | Yes | N/A | Not a concept in OpenSCAD |
| Sleep/blocking calls | Yes (AST) | Yes | Yes | N/A | Not a concept in OpenSCAD |
| Absolute paths in strings | Yes | Yes | Yes | Yes (in include<>/use<>) | /home/, /Users/, C:\ |
| Hardcoded credentials | Yes | Yes | Yes | Yes | api_key, secret_key, password, etc. |
| Hardcoded IPs | Yes | Yes | Yes | No | N.N.N.N pattern |
| eval() | No | Yes | N/A | N/A | JS-specific |
| C FFI pragmas ({.importc.}, {.compile.}) | N/A | N/A | Yes | N/A | Nim-specific |
| Global mutable state ({.global.}) | N/A | N/A | Yes | N/A | Nim-specific |
| when isMainModule | N/A | N/A | Yes | N/A | Nim-specific |
| OS-specific when defined() | N/A | N/A | Yes | N/A | Nim-specific |
| Risky stdlib imports | N/A | Yes (fs, child_process, etc.) | Yes (os, osproc, etc.) | N/A | Python does not block these |
| Top-level geometry/control flow | N/A | N/A | N/A | Yes (src/ only) | Bleeds into consumer's scene |
| include<> | N/A | N/A | N/A | Yes (src/ local only) | Executes full file on import; use use<>. External declared deps allowed. |
| Global resolution ($fn/$fa/$fs) | N/A | N/A | N/A | Yes (src/ only) | Steals consumer's quality settings |

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

### OpenSCAD

| Check | Fails if | Method |
|-------|----------|--------|
| Renders to non-empty STL | exit non-zero or STL <= 84 bytes | subprocess (openscad -o tmp.stl) |
| No top-level geometry or control flow in src/ | present | regex + brace-depth tracker |
| All module parameters have defaults | any param missing `= value` | regex, bracket-aware split |
| No `include <>` in src/ | present | regex (use `use <>` instead) |
| No `echo()` in src/ | present | regex, comment-aware |
| No `$fn`/`$fa`/`$fs` assignments in src/ | present | regex, comment-aware |

**Coverage:** None enforced. Render passes = validation passes (same as Nim).

**Native scanner:** Python fallback (OpenSCAD has no file I/O — cannot write a scanner in the language itself).

**Contamination scanner scope:** src/ only for structural checks. All files checked for absolute paths and credentials.

### Warnings (OpenSCAD)

| Pattern | Notes |
|---------|-------|
| Hardcoded URLs in src/ | Excludes localhost, example.com |
| Unlisted library in use<> | Not declared in widget.json dependencies |
| Module parameters without unit comments | Add `// mm`, `// degrees`, etc. |
| Missing Customizer annotations in examples | Add `/* [Section] */` blocks with value ranges |

## Decisions and Known Limitations

**Why no risky import blocking for Python?**
Python's stdlib (os, subprocess, etc.) is commonly used in legitimate widget code. Blocking it would make most widgets invalid. JS and Nim block their equivalents because those ecosystems have different conventions around filesystem access.

**Why Nim has more checks than others?**
Nim's compilation model (compiles to C, links native) means more things can go wrong portably. Platform-specific `when defined()`, C FFI, and global state are Nim-specific concerns.

**Why line-based scanning for Nim instead of AST?**
The line-based scanner uses only stdlib and has no compiler dependencies. If false positives become a problem, AST parsing via `compiler/parser` can be revisited.

**Why no top-level variables in OpenSCAD src/?**
A widget is a module definition. Variables assigned at the top level of a .scad file bleed into every file that `use`s it, polluting the consumer's namespace. Same principle as "no global state" in Python/Nim widgets. Everything belongs inside a module.

**Why block `include <>` for local files in OpenSCAD src/?**
`include <>` executes the entire included file as if it were pasted in - variables, geometry, and all. `use <>` only imports module definitions. A widget should never use `include <>` on local relative paths; `use <>` is always the right choice for local library code.

Exception: `include <ExternalLib/file.scad>` is allowed when the library is declared in `widget.json` dependencies (e.g. `include <BOSL2/std.scad>`). External libraries like BOSL2 require `include` to expose their constants (`CENTER`, `UP`, etc.) and this is intentional — consumers of a BOSL2 widget expect those constants to be in scope.

**Why block `$fn`/`$fa`/`$fs` in OpenSCAD src/?**
These are global resolution settings. A widget setting `$fn = 100` in src/ overrides the consumer's quality settings for their entire scene. Expose resolution as a module parameter instead (`fn = 32`) so consumers control it.

**Why does the BOSL2 doctor check render a test file instead of just checking the directory?**
Directory existence is not sufficient — OpenSCAD's library search path must also include the parent directory. A user could clone BOSL2 to the right location but have a stale `OPENSCADPATH` that shadows it, or the clone could be corrupt. The check renders `use <BOSL2/std.scad> sphere(r=1, $fn=4);` to a temp STL — if it produces geometry, BOSL2 is genuinely usable. `OPENSCADPATH` is also checked for non-standard installs.

**Why is the OpenSCAD top-level check depth-based instead of AST?**
OpenSCAD has no stdlib parser accessible from Python. A brace-depth tracker catches all practical cases (bare geometry, `if`/`for`/`let` blocks). Known limitation: geometry inside a top-level `if` where the `{` and `}` are on separate lines is caught; single-line `if(true) cube(...)` without braces is not currently detected.

**Why tests run twice if users want custom test flags?**
Custom rules can call the test runner again with their preferred flags (testament --megatest, pytest --benchmark, etc.). Tests run once our way (the quality guarantee), once their way (their preferences). This avoids the complexity of flag merging and keeps the base validation clean.
