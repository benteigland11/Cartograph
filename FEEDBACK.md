# Cartograph Developer Feedback
> Written after scaffolding a FastAPI backend using ~7 installed widgets and contributing 2 new ones.

---

## Bug 1 — Dependency version pin validator gives false rejection

**Severity: High** — blocks `cartograph validate` and `cartograph checkin`

### What happened
When filling out `widget.json` for a new widget with a FastAPI dependency, I wrote:

```json
"dependencies": [
  { "name": "fastapi", "version": ">=0.128.0" }
]
```

The validator rejected it with:

```
"Dependency 'fastapi' has no version pin — use 'fastapi>=<version>' for reproducibility"
```

The version *is* pinned. The format `>=0.128.0` is valid and exactly what the error message tells you to use. Running validate again after double-checking the JSON produced the same rejection. The value in the file and the value the error asks for are identical.

### What I'd expect
The validator should accept `>=X.Y.Z`, `==X.Y.Z`, and `~=X.Y.Z` as valid pins and only reject a missing or empty `version` field.

### Likely fix
The version check regex or comparison logic is probably matching against the raw version string (`>=0.128.0`) instead of stripping the operator first before checking for emptiness. Something like:

```python
# broken — treats ">=0.128.0" as unpinned
if not dep["version"]:
    raise ValidationError(...)

# fixed — strip operator before checking
version_value = re.sub(r'^[><=!~]+', '', dep["version"]).strip()
if not version_value:
    raise ValidationError(...)
```

### Workaround I used
Removed the dependency entirely and refactored the widget to use `Protocol`-based duck typing instead of importing from `fastapi` directly. Made the widget better in hindsight, but the path there was a false error.

---

## Bug 2 — `cartograph create` generates stub test files that break pytest collection

**Severity: Medium** — doesn't block anything but requires manual cleanup

### What happened
After running `cartograph create backend-websocket-broadcaster-python`, the scaffold included an auto-generated stub test file:

```
tests/test_websocket_broadcaster.py
```

That file tried to import a module that doesn't exist yet:

```python
from src.websocket_broadcaster import websocket_broadcaster
```

I then wrote my own real test file `tests/test_broadcaster.py`. When running `pytest`, the stub file caused a collection error that stopped the entire suite — pytest doesn't skip files with import errors, it aborts.

### What I'd expect
Either:
- The stub test file should be clearly marked as a placeholder with a comment like `# TODO: replace this stub` and contain a single passing `test_placeholder` that imports nothing
- Or the stub should not be generated at all — an empty `tests/` directory is less disruptive than a broken one

### Likely fix
Change the stub template from:

```python
from src.{module_name} import {module_name}
```

to:

```python
def test_placeholder():
    """Replace this with real tests."""
    pass
```

Or check if the module name after stripping the widget ID prefix actually exists in `src/` before generating the import.

---

## Issue 3 — Example import format is strict but undocumented

**Severity: Low** — easy to fix once you know the rule, but wastes time discovering it

### What happened
The validator requires example files to import using this exact pattern:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.mymodule import MyClass
```

My first attempt added `src/` directly to the path and imported the module by name:

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mymodule import MyClass
```

The validator rejected this with `"examples/example_usage.py must import from src/"`. The error message is correct but doesn't tell you *how* to import from `src/` — only that you must. I found the correct pattern by inspecting an existing widget's example with `cartograph inspect`.

### What I'd expect
The error message should show the expected import pattern, not just the rule:

```
examples/example_usage.py must import from src/

Expected pattern:
  sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
  from src.mymodule import MyClass
```

Alternatively, document this in the `library_notes` field of `widget.json` — it's the natural place a contributor looks when writing examples.

---

## General notes (positive)

- The installed widgets were all solid. `backend-sqlite-python`, `backend-sqlite-repository-python`, `backend-response-envelope-python`, `backend-work-queue-python`, `infra-config-loader-python`, and `backend-request-validator-python` all had APIs that exactly matched their `inspect` output. No surprises.
- `cartograph inspect --source` before installing is genuinely useful — being able to read the implementation before committing to it is a good workflow.
- The `checkin --reason` prompt is good friction. It forces a one-line description that doubles as useful context in the widget registry.
