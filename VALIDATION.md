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
| SystemVerilog | No | N/A | Testbench `$finish` exit code = pass; no per-line coverage |

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

### PHP

| Check | Fails if | Method |
|-------|----------|--------|
| composer.json exists | missing | file check |
| phpunit.xml exists | missing | file check |
| PHP syntax valid | parse error in any src/ file | `php -l` per file |
| All declared dependencies are version-pinned | unpinned dep found | dep pinning check |
| Contamination scan passes on src/ | issues found | Python-based scanner |
| PHPUnit tests pass | any test fails | `vendor/bin/phpunit` |
| Coverage meets threshold | below 80% | `--min-coverage=80` flag |
| Example runs and exits cleanly | non-zero exit | `php examples/example_usage.php` |

**Coverage:** 80% enforced via `--min-coverage=80` PHPUnit flag. Requires Xdebug or PCOV installed as a PHP extension. The validator checks for both extensions before running tests and returns a clear error if neither is found. `check_optional()` surfaces coverage driver status in `cartograph doctor`.

**Test runner:** `php vendor/bin/phpunit --coverage-text --coverage-filter=src --min-coverage=80`. PHPUnit is installed as a dev dependency via Composer.

**Example validation:** `php examples/example_usage.php` - runs and exits cleanly (same as Python). No build step.

**Scanner:** Python-based line scanner (PHP has no file I/O limitation, but the Python scanner covers all required checks accurately for PHP's syntax). Key checks:

- `echo` in src/ files blocked (same rule as Python `print()`)
- WordPress globals blocked everywhere: `wp_*`, `add_action`, `add_filter`, `do_action`, `apply_filters`, `register_post_type`, `register_taxonomy`, `get_option`, `update_option`, `$wpdb`, `$wp_query`, `$post`, `$current_user` - these make PHP untestable outside WordPress
- Hardcoded credentials blocked in src/, warned in tests
- Absolute paths blocked everywhere
- Hardcoded IPs blocked in src/
- Hardcoded URLs warned in src/
- `sleep()`/`usleep()` blocked in src/, large values warned in tests
- `getenv()`/`$_ENV`/`$_SERVER` access warned in src/
- Hardcoded constant assignments warned in src/
- Unlisted namespace imports are resolved against composer's authoritative
  autoload table (`vendor/composer/autoload_psr4.php`,
  `autoload_namespaces.php`, `autoload_classmap.php`). A `use` whose root
  namespace is not in that table genuinely cannot be resolved at runtime, so
  it **blocks in src/** and **warns in tests/examples**. If the autoload
  table is unavailable (e.g. `composer install` hasn't run), the scanner
  falls back to a vendor-prefix heuristic at warning severity only.

**No native scanner:** The Python scanner handles PHP contamination accurately. PHP's string and comment syntax is simple enough for line-based checks, and WordPress globals are identifiable by name without AST parsing.

### Angular

| Check | Fails if | Method |
|-------|----------|--------|
| angular.json exists | missing | file check |
| package.json exists | missing | file check |
| karma.conf.js exists | missing | file check |
| ng-package.json exists | missing | file check |
| Native JS scanner passes on src/ | issues found | js_scanner.js (reused for TypeScript) |
| All declared dependencies are version-pinned | unpinned dep found | dep pinning check |

**Coverage:** 80% enforced via `karma.conf.js` `check.global` thresholds (statements, branches, functions, lines). Karma exits non-zero when thresholds are not met; the validator detects the "does not meet global threshold" string in output and surfaces a coverage-specific error message.

**Test runner:** `ng test --watch=false --no-progress` — Karma + Jasmine in ChromeHeadlessNoSandbox. Chrome or Chromium must be installed on the system. The karma.conf.js in the scaffold configures `--no-sandbox --disable-gpu` for CI compatibility.

**Example validation:** Angular components cannot be executed as scripts. `run_example` calls `ng build <project>` (build artifact pattern, same as OpenSCAD's render check). `examples/example_usage.ts` is included in `tsconfig.lib.json` so TypeScript type errors in the example will also fail the build.

**Scanner:** Reuses `js_scanner.js` since Angular uses TypeScript syntax. All standard JS contamination checks apply: console.log, eval, absolute paths, credentials, hardcoded URLs/IPs, env var access, unlisted imports, sleep/blocking.

**Angular-specific contamination rules (language_notes, not scanner):**
- Component selectors must be generic: `lib-item`, `lib-counter` - not `lib-mycompany-header`
- No project-specific class names in decorators: `@Component`, `@Injectable`, `@NgModule`
- URL parameters belong in examples/ as demonstration data, not hardcoded in component logic

### SystemVerilog

| Check | Fails if | Method |
|-------|----------|--------|
| src/ has .sv files | missing | file check |
| Lint passes | syntax/semantic errors | iverilog -g2012 -Wall -tnull |
| Each tests/test_*.sv compiles and simulates | iverilog or vvp non-zero exit | iverilog + vvp subprocess |
| examples/example_usage.sv compiles and simulates | iverilog or vvp non-zero exit | iverilog + vvp subprocess |
| Python fallback contamination scanner passes | issues found | regex + block_walker primitives |

## Contamination Scanning

Each language has a native scanner written in that language (not regex from Python).
Python uses AST parsing. JS uses a token-based parser. Nim uses line-based scanning with string/comment awareness.

### Scoping rule

The scanners use three file-location scopes: `src/`, `tests/`, `examples/`.
The unifying rule for contamination checks:

- **Tests skip fixture-style warnings** (hardcoded values, URLs, IPs).
  Tests legitimately use mock data, expected values, and fake endpoints.
- **Tests keep real safety nets** (absolute home paths, credentials,
  unlisted imports). A real secret or real user path in a test is still
  wrong.
- **Examples are not scanned** - they are validated by being executed
  (Python/JS/Nim) or rendered (OpenSCAD/SV), not by static scanning.

**Unlisted imports policy (all languages):** an import that is not in
widget.json `dependencies`, not stdlib, and not a local src/ module is
a **block in src/** and a **warning in tests/examples**. The rationale
is uniform: an unlisted dep means the widget breaks on install for
anyone else. The fix is trivial (add to `dependencies` or remove the
import), so there is no override.

**Resolver ground truth, not convention.** Where a language's package
manager can answer "what namespaces/modules can actually be resolved?",
the scanner asks it directly instead of relying on naming conventions:

- Python: `importlib.metadata.packages_distributions()` (maps import
  name to installed package, handling `python-docx` -> `docx` etc.)
- PHP: `vendor/composer/autoload_*.php` tables (same source PHP's own
  runtime uses)

Languages where naming convention is contractual (JS npm name = import
specifier; Nim nimble pkg = import root) use the simpler declared-deps
comparison - the resolver would give the same answer with more code.

**Why not a JS resolver?** npm package name is the import specifier by
spec, not convention - `package.json` `name` field is canonical and the
import string matches it exactly (including scoped `@org/pkg` forms).
Walking `node_modules/*/package.json` would return the same answer as
comparing against widget.json's declared deps. Worse, it would also
surface transitive dependencies installed under `node_modules/` that
the widget never declared - actively weakening contamination detection.
A widget that imports a transitive it shouldn't rely on would stop
being flagged. The resolver pattern is only valuable when it catches
real false positives; JS has none.

Test frameworks are a separate concern: `vitest`, `jest`, `mocha`, etc.
live in `package.json` devDependencies, not widget.json. They are
allowlisted in test/example files by `TEST_FRAMEWORKS` in the scanner
so users don't have to override every checkin or duplicate them into
widget.json.

**Why not an OpenSCAD resolver?** OpenSCAD "dependencies" are shared
library directories (BOSL2, MCAD) dropped into `OPENSCADPATH`. There is
no translation layer - `include <BOSL2/std.scad>` has `BOSL2` as its
first path segment, which is exactly what widget.json declares. No
mismatch possible. Beyond that, the validation pipeline runs an actual
OpenSCAD render against the example, so any unresolved include fails
with a real render error, not a static guess. The render is strictly
more authoritative than any resolver we could write.

**Why not a Nim resolver?** nimble enforces by spec that a package
named `foo` must publish a top-level `foo.nim`, and `import foo`
resolves to exactly that. The import root always matches the nimble
package name. Popular packages (`chronos`, `jester`, `nimcrypto`,
`karax`, `zippy`) all follow this without exception. An additional
concern: nimble installs into a global `~/.nimble/pkgs/` path, so
walking it would pull every package the user has ever installed
system-wide into the "provided" set - hiding real undeclared-dep
contamination rather than catching it. Nim's `std/unittest` lives
in the stdlib allowlist and needs no special handling.

### Fails validation if found (src/ only unless noted)

| Pattern | Python | JS | Nim | OpenSCAD | SystemVerilog | Notes |
|---------|--------|----|-----|----------|---------------|-------|
| Debug output (print/echo/console.log) | Yes (AST, src/ only) | Yes (src/ block, tests/ warn, examples/ allow) | Yes (src/ block, tests/ warn, examples/ allow) | Yes (echo(), src/ only) | Yes ($display/$monitor/$write/$strobe in src/) | |
| Process exit (sys.exit/process.exit/quit) | Yes (AST) | Yes | Yes | N/A | N/A | Not a concept in OpenSCAD or RTL |
| Sleep/blocking calls | Yes (AST) | Yes | Yes | N/A | Yes (`#delay`, src/ only) | RTL: simulation timing belongs in testbench |
| Absolute paths in strings | Yes (src+tests block) | Yes (src+tests block) | Yes (src+tests block) | Yes (in include<>/use<>) | Yes (in $readmemh/$readmemb) | /home/, /Users/, C:\ — blocked in tests too (use tmp_path fixtures) |
| Hardcoded credentials | Yes (src block, tests warn) | Yes (src block, tests warn) | Yes (src block, tests warn) | Yes | Yes | api_key, secret_key, password, etc. |
| Hardcoded IPs | Yes (src/ only) | Yes (src/ only) | Yes (src/ only) | No | No | N.N.N.N pattern — skipped in tests (mock fixtures) |
| eval() | No | Yes | N/A | N/A | N/A | JS-specific |
| C FFI pragmas ({.importc.}, {.compile.}) | N/A | N/A | Yes | N/A | N/A | Nim-specific |
| Global mutable state ({.global.}) | N/A | N/A | Yes | N/A | N/A | Nim-specific |
| when isMainModule | N/A | N/A | Yes | N/A | N/A | Nim-specific |
| OS-specific when defined() | N/A | N/A | Yes | N/A | N/A | Nim-specific |
| Risky stdlib imports | N/A | Yes (fs, child_process, etc.) | Yes (os, osproc, etc.) | N/A | N/A | Python does not block these |
| Unlisted imports | Yes (AST + `packages_distributions`) | Yes | Yes | Yes (include<>/use<>) | N/A | src/ blocks, tests/examples warn. PHP uses composer autoload tables - see PHP section. |
| Top-level geometry/control flow | N/A | N/A | N/A | Yes (src/ only) | N/A | Bleeds into consumer's scene |
| include<> | N/A | N/A | N/A | Yes (src/ local only) | N/A | Executes full file on import; use use<>. External declared deps allowed. |
| Global resolution ($fn/$fa/$fs) | N/A | N/A | N/A | Yes (src/ only) | N/A | Steals consumer's quality settings |
| `initial` blocks | N/A | N/A | N/A | N/A | Yes (src/ only) | Simulation-only, not synthesizable |
| `` `timescale `` directive | N/A | N/A | N/A | N/A | Yes (src/ only) | Belongs in testbench |
| Verilog-2001 `always @(...)` | N/A | N/A | N/A | N/A | Yes (src/ only) | Use always_comb / always_ff |
| Vendor primitives (LUT6, BUFG, RAMB36, ALTPLL, sky130, ...) | N/A | N/A | N/A | N/A | Yes unless declared | Allowed if vendor lib in widget.json deps |
| Blocking `=` in always_ff | N/A | N/A | N/A | N/A | Yes | Race condition on synthesis |
| Non-blocking `<=` in always_comb | N/A | N/A | N/A | N/A | Yes | Wrong semantics for combinational |
| Hardcoded file paths in $readmemh/$readmemb | N/A | N/A | N/A | N/A | Yes | Parameterize the path |

### Warnings (overridable)

Unless otherwise noted, warnings are **src/ only** — the scoping rule
above applies.

| Pattern | Python | JS | Nim | SystemVerilog | Scope | Notes |
|---------|--------|----|-----|---------------|-------|-------|
| Hardcoded URLs | Yes | Yes | Yes | Yes | src/ only | Excludes localhost, example.com, .test |
| Hardcoded values (constants) | Yes (AST) | Yes (config-like names) | Yes | Yes (sized literals like 32'd115200, 8'hFF; typedef enum bodies excluded) | src/ only | Fixture values in tests are expected |
| Environment variable access | Yes | Yes | Yes | N/A | src + tests | os.getenv, process.env, getEnv |
| Old-style stdlib imports | No | No | Yes | N/A | src + tests | `import json` vs `import std/json` |
| Top-level mutable state | No | No | Yes | N/A | src/ only | `var` at module level |
| Credentials in tests | Yes | Yes | Yes | Yes | tests/ | Lowered from block → warn in tests |

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

### SystemVerilog

| Check | Fails if | Method |
|-------|----------|--------|
| Lints under iverilog -g2012 | syntax/semantic errors | iverilog -Wall -tnull |
| No `initial` blocks in src/ | present | regex (comment-stripped) |
| No `#delay` in src/ | present | regex (comment-stripped) |
| No `` `timescale `` directive in src/ | present | regex (comment-stripped) |
| No Verilog-2001 `always @(...)` in src/ | present | regex |
| No $display/$monitor/$write in src/ | present | regex |
| No vendor primitives unless declared | undeclared use | regex with vendor-key allowlist |
| No blocking `=` in always_ff bodies | present | block_walker extracts always_ff blocks, line scan |
| No non-blocking `<=` in always_comb bodies | present | block_walker extracts always_comb blocks, line scan |
| No hardcoded paths in $readmemh/$readmemb | present | regex |
| Each tests/test_*.sv simulates to clean exit | iverilog or vvp non-zero | iverilog + vvp |
| examples/example_usage.sv simulates to clean exit | iverilog or vvp non-zero | iverilog + vvp |

**Coverage:** None enforced. Successful simulation (testbench reaches `$finish`) = validation passes.

**Native scanner:** Python fallback. Icarus Verilog has no scriptable AST API and SystemVerilog parsers in Python (e.g. pyverilog) are heavy and incomplete. The scanner uses regex for token matches and dogfoods the `universal-block-walker-python` widget for depth-aware extraction (always_ff/always_comb bodies, typedef enum bodies).

**Contamination scanner scope:** src/ only for structural checks. All files checked for absolute paths and credentials.

### Warnings (SystemVerilog)

| Pattern | Notes |
|---------|-------|
| Hardcoded URLs in src/ | Excludes localhost, example.com |
| Hardcoded sized literals | e.g. 32'd115200, 8'hFF — should be parameters. typedef enum bodies excluded. |
| Hardcoded credentials in tests | "verify it's fake" — same rule as other languages |

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

**Why no coverage enforcement for SystemVerilog?**
Coverage in RTL means functional/assertion/toggle coverage and is a property of the testbench, not the source. Icarus Verilog does not produce line coverage in any form Cartograph could enforce uniformly. The bar is the same as OpenSCAD: a successful simulation that reaches `$finish` is the validation. Testbenches are expected to use `$fatal(1, ...)` on assertion failure so non-zero exit codes propagate.

**Why block `initial`, `#delay`, and `timescale` in src/ but allow them in tests/?**
These are simulation-only constructs. `initial` blocks and `#delay` are not synthesizable — they cannot be turned into hardware. A widget's src/ must be synthesizable RTL; the testbench owns all simulation timing. `timescale` is a tool directive that belongs once per simulation, in the testbench, so a consumer's project sets the global timescale instead of inheriting one per widget.

**Why block legacy `always @(...)` in src/ but use `always_ff` / `always_comb`?**
Verilog-2001 `always @(posedge clk)` and `always @*` rely on the writer to remember whether a block is sequential or combinational. SystemVerilog's `always_ff` and `always_comb` make the intent explicit and let tools catch incorrect sensitivity lists or missing assignments. Widget code must be unambiguous about intent — if you wrote `always_ff` you mean a flip-flop, full stop.

**Why check blocking vs non-blocking assignments per always block?**
Mixing `=` (blocking) inside an `always_ff` (sequential) block introduces simulation/synthesis mismatches that are notoriously hard to debug — the simulator may show one schedule and the synthesized hardware another. Similarly, `<=` inside `always_comb` produces a latch in synthesis. The scanner uses `block_walker.extract_blocks` to find each always block's body and then checks line statements. For-loop headers are skipped because the loop variable `=` is not a signal assignment.

**Why allow vendor primitives only when declared in dependencies?**
Vendor primitives like Xilinx `LUT6` or Intel `ALTPLL` lock a widget to one FPGA family and require the vendor's simulation library to even compile. If a widget genuinely needs them, declaring `xilinx-unisim` (or similar) in `widget.json` makes the dependency explicit so consumers know what toolchain they're committing to. Generic, portable RTL is the default expectation.

**Why dogfood the `universal-block-walker-python` widget instead of inlining the parser?**
Both OpenSCAD and SystemVerilog need depth-aware text walking (matching `{`/`}`, `(`/`)`, `begin`/`end`) that respects strings and comments. Maintaining two copies of that logic would drift. The block_walker widget is the shared primitive — it gets exercised by every SV and OpenSCAD validation, which is the strongest possible regression test for it.
