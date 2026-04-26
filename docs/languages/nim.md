# Cartograph for Nim

> What Cartograph does to your Nim code when you run `validate` or `checkin`,
> and why each check exists.

This doc is a contract. If a rule fires on your widget, it is documented
here with its rationale. Nothing is hidden in the engine.

## At a glance

| Field             | Value                                                  |
| ----------------- | ------------------------------------------------------ |
| Domain(s)         | any (commonly `backend`, `data`, `infra`, `ml`)        |
| File extension    | `.nim`                                                 |
| Manifest          | `<widget_id>.nimble` at the widget root                |
| Compiler required | `nim` 2.0+ (run `cartograph doctor` to check)          |
| Test runner       | `nimble test`                                          |
| Test framework    | `std/unittest` (required)                              |
| Coverage          | not enforced (Nim has no first-class coverage tool)    |
| Contamination     | native `nim_scanner.nim` over `src/`, `tests/`, `examples/` |
| Custom rules      | Nim script at `.cartograph/rules/rules.nim`            |
| Policy            | pure Nim — no FFI; C bindings go through nimble        |

Engine source: `src/cartograph/languages/nim.py`.
Scanner source: `src/cartograph/languages/scanners/nim_scanner.nim`.

## Pipeline

`cartograph validate` and `cartograph checkin` run these stages in order.
Any failure stops the run.

1. **Required files** — there must be a `<widget>.nimble` at the widget
   root and at least one `.nim` file in `src/`.
2. **`nim check`** — runs over every `src/**.nim`. Catches type errors,
   undefined symbols, bad syntax. `--hints:off --warnings:off`. Output
   that mentions "cannot find module" is suppressed (those are caught by
   the import scan instead).
3. **`nim c --compileOnly`** — compiles every src file without running.
   Catches link-time and codegen issues that `nim check` misses.
4. **Contamination scan** — `nim_scanner.nim` walks every `.nim` file in
   `src/`, `tests/`, `examples/` and emits structured findings. See
   *Rule reference* below.
5. **Dependency pinning** — every entry in `widget.json -> tech_stack.dependencies`
   must have a version operator (`>=`, `==`, `~=`, `<=`, `!=`). Bare
   names like `chronos` are rejected; `chronos >= 4.0` passes.
6. **Custom rules** — if `.cartograph/rules/rules.nim` (per project) or
   the global rules file exists, it runs and its findings are merged in.
7. **Tests** — `nimble test -y`, with `NIMBLE_DIR` pointed at an
   isolated temp dir (see *Isolation*).

`nim check` and `nim c` both write to a per-validation `--nimcache:` dir
in `/tmp`, so validation works in environments where `$HOME` is
read-only (Codex, restricted devcontainers, CI sandboxes).

## Widget layout

`cartograph create my-widget --domain backend --language nim` produces:

```
backend-my-widget-nim/
  widget.json
  my-widget.nimble
  src/
    my_widget_lib.nim     # the *_lib suffix avoids stdlib name collisions
  tests/
    test_my_widget.nim
  examples/
    example_usage.nim
```

The `_lib` suffix on the src module name is deliberate: Nim's stdlib
modules resolve before `--path:src`, so naming your file `os.nim` or
`strutils.nim` would shadow the stdlib in surprising ways. Tests and
examples import the suffixed name explicitly.

## Style requirements

These come from `library_config.json -> language_notes.nim` and are part
of what Cartograph and consumers expect from a Nim widget. Some are
enforced by the scanner; others are conventions reviewers will check.

| Requirement                                   | Enforced by              |
| --------------------------------------------- | ------------------------ |
| `import std/unittest` for tests               | scaffold + convention    |
| `func` for pure procs, `proc` only with side effects | convention         |
| Public symbols marked with `*` (e.g. `func foo*(...)`) | convention      |
| camelCase for funcs/procs/vars, PascalCase for types | convention        |
| `import std/strutils` over bare `import strutils` | scanner (`std_import_style`) |
| Generic identifiers — no project-specific names | convention             |
| No FFI pragmas (`{.importc.}`, `{.compile.}`) | scanner (`ffi`)          |
| No `{.global.}` mutable state                 | scanner (`global`)       |
| No `when defined(<os>)` branching             | scanner (`os_specific`)  |
| `<widget_id>.nimble` present at widget root   | required-files check     |

## Severity levels

| Severity   | Meaning                                                    | Stops checkin? |
| ---------- | ---------------------------------------------------------- | -------------- |
| `block`    | Hard policy violation (sleep in `src/`, absolute path)     | yes            |
| `error`    | Rule violation (`quit`, FFI pragma, `when isMainModule`)   | yes            |
| `warning`  | Advisory; surfaces in the report but does not fail the run | no             |

Tests and examples get more lenient severities for the same patterns —
fixtures, demo constants, and debug `echo` are common there.

## Rule reference

Every rule the scanner enforces today, with severity by location.

### Structural

| Rule              | What fires it                              | src   | tests | examples |
| ----------------- | ------------------------------------------ | ----- | ----- | -------- |
| `main_module`     | `when isMainModule:` block                 | error | error | error    |
| `top_level_var`   | `var foo = ...` at module scope            | warn  | -     | -        |
| `global`          | `{.global.}` pragma                        | error | error | error    |
| `os_specific`     | `when defined(windows)` / `linux` / etc.   | error | error | error    |

Rationale: widgets are libraries, not programs. A widget that only works
on one OS, or carries hidden global state, breaks the "drop in and use"
contract.

### FFI and memory safety

| Rule         | What fires it                                   | src   | tests | examples |
| ------------ | ----------------------------------------------- | ----- | ----- | -------- |
| `ffi`        | `{.importc.}` or `{.compile.}` pragma           | error | error | error    |
| `cast_seq`   | `cast[seq[T]](...)`                             | block | warn  | warn     |
| `raw_memory` | `alloc`, `dealloc`, `copyMem`, `cast[ptr ...]`, `ptr UncheckedArray` | warn  | warn  | warn     |

Rationale: Cartograph's Nim widgets are pure Nim by design. C bindings
belong in a nimble package the widget depends on — that way the binding
gets versioned and reused, instead of being duplicated inline. `cast[seq[T]]`
is a memory-safety hazard because Nim seqs carry a GC header; raw memory
primitives warn because legitimate uses exist but are rare.

### Imports

| Rule                | What fires it                                          | src   | tests | examples |
| ------------------- | ------------------------------------------------------ | ----- | ----- | -------- |
| `risky_import`      | `std/os`, `std/osproc`, `std/httpclient`, `std/net`, `std/nativesockets` | error | error | error    |
| `std_import_style`  | `import strutils` instead of `import std/strutils`     | warn  | warn  | warn     |
| `unlisted_import`   | Importing a package not in `widget.json`               | block | warn  | warn     |

The scanner handles every form of Nim import: bare, `std/`, comma lists,
`std/[a, b, c]` brace groups, multi-line continuations, `from ... import`,
`as` aliases, `except` clauses. It also allowlists local modules in
`src/` (so `tests/` can `import my_widget_lib`) and resolves relative
imports (`./foo`, `../src/foo`).

### Runtime hazards

| Rule          | What fires it                                          | src   | tests          | examples       |
| ------------- | ------------------------------------------------------ | ----- | -------------- | -------------- |
| `quit`        | `quit(...)` or `system.quit(...)`                      | error | error          | error          |
| `echo`        | `echo` statement                                       | error | warn           | -              |
| `sleep`       | `sleep()`, `sleepAsync()`, `os.sleep()`                | block | warn (>1000ms) | warn (>1000ms) |
| `bare_except` | `except:` or `except: discard`                         | warn  | warn           | warn           |
| `env_var`     | `getEnv`, `envPairs`                                   | warn  | warn           | warn           |

### Hardcoded values

| Rule              | What fires it                                                  | src   | tests | examples |
| ----------------- | -------------------------------------------------------------- | ----- | ----- | -------- |
| `abs_path`        | `"/home/..."`, `"/Users/..."`, `"C:\\..."` in a string         | block | block | block    |
| `credential`      | `api_key`, `secret_key`, `password` etc. assigned a string     | block | warn  | warn     |
| `hardcoded_url`   | `"http://..."` or `"https://..."` (excludes localhost, .test)  | warn  | -     | -        |
| `hardcoded_ip`    | IPv4 literal in a string                                       | block | -     | -        |
| `hardcoded_value` | `let foo = 42` or `let s = "literal"` at module scope          | warn  | -     | -        |

Rationale: a widget with `/home/alice/data` baked into a string is not
reusable. Tests and examples are exempt for the values that legitimately
belong there (mock URLs as fixtures, demo constants, expected values).

## Dependencies

Nimble dependencies are declared once in `widget.json`:

```json
{
  "tech_stack": {
    "dependencies": ["chronos >= 4.0", "stew >= 0.4"]
  }
}
```

What the engine does with that list:

- **Pin check.** Each entry must have a version operator (`>=`, `==`,
  `~=`, `<=`, `!=`). `chronos` alone fails; `chronos >= 4.0` passes.
- **`.nimble` sync.** On checkin, Cartograph rewrites the `requires`
  lines in `<widget>.nimble` to match `widget.json`. Do not hand-edit
  `requires` lines — they will be overwritten.
- **Install.** Each dep is installed with `nimble install -y <name>`
  into an isolated `NIMBLE_DIR` (see *Isolation*).
- **Allowlist.** The scanner's `unlisted_import` check reads this list
  and treats anything in it as a known dep.

## Isolation

Validation runs are sandboxed so they don't touch your normal nimble
setup:

| What        | Where                                | Cleaned up after run |
| ----------- | ------------------------------------ | -------------------- |
| `NIMBLE_DIR`| `/tmp/cartograph_nim_XXXX/`          | yes                  |
| nim cache   | `/tmp/cartograph_nimcache_XXXX/`     | yes                  |
| Compiled binaries left by `nimble c -r` in `tests/` and `examples/` | (in widget tree) | yes — ELF/Mach-O/PE detected by header bytes and removed |

Your `~/.nimble` is never modified by Cartograph.

## Common failures and fixes

**`unlisted_import: import chronos`** — add `chronos >= <version>` to
`widget.json -> tech_stack.dependencies`. The scanner reads that list and
allowlists everything in it.

**`Dependency 'chronos' has no version pin`** — bare names are rejected
for reproducibility. Use `chronos >= 4.0`.

**`risky_import: import std/os`** — `std/os` is flagged for review, not
forbidden outright. If your widget genuinely needs filesystem access,
state why in the checkin reason.

**`ffi: {.importc.}`** — move the C binding into its own nimble package,
publish it, then add the package to `tech_stack.dependencies`. The
widget itself stays pure Nim.

**`top_level_var` triggered on a multi-line `proc` signature** — known
scanner bug fixed in v0.6.16. Update Cartograph if you see it on code
that is not actually a top-level `var`.

**`hardcoded_value: let MAX_RETRIES = 3`** — accept it as a parameter
with a default instead of hardcoding it at module scope.

**`nim check` fails with "cannot find module my_widget_lib"** — your
test or example is importing the bare name, but the file is at
`src/my_widget_lib.nim`. The scaffolded test does `import my_widget_lib`
and works because `nimble test` adds `--path:src`. If you run `nim check`
manually, pass `--path:src` too.

**`nim` not found / `~/.nimble` is read-only** — Cartograph runs
`nim` and `nimble` in an isolated env that does not need write access
to `$HOME`. If you're seeing this, check that `nim --version` works in
your shell; Cartograph just shells out.

## Custom rules

To add Nim-specific rules that run alongside the built-in scanner:

```
cartograph rules init --language nim
```

This drops a template into `.cartograph/rules/rules.nim` (per project)
or the global rules dir (with `--global`). The file is a plain Nim
script — no special API. Cartograph runs it with
`nim r --hints:off <rules.nim> <widget_path>` and reads JSON from
stdout:

```nim
import std/[json, os, strutils]

proc validate(widgetPath: string): JsonNode =
  var blocks = newJArray()
  var warnings = newJArray()

  # add your checks here
  # blocks.add(%*"hard failure message")
  # warnings.add(%*"soft warning message")

  result = %*{"blocks": blocks, "warnings": warnings}
```

`blocks` reject the checkin (no override). `warnings` are overridable
with `--override-warnings`. Custom rules **add** checks; they cannot
relax the built-ins above.

## Reference

- Engine: `src/cartograph/languages/nim.py`
- Scanner: `src/cartograph/languages/scanners/nim_scanner.nim`
- Library config (style notes): `src/cartograph/library_config.json`
- Custom-rules dispatch: `src/cartograph/rules.py`
- Pure-Nim policy: `project_nim_pure_policy.md` (project memory)
- Example widgets: `cartograph search --language nim`
