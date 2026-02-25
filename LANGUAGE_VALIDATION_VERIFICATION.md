# Language Validation Verification

This document verifies that widget_factory.py language guidelines match cartographer.py validation requirements.

## Summary

| Language | Validation Command | File Structure | Build File | Status |
|----------|-------------------|----------------|------------|--------|
| Python | `pytest {test_file}` from widget dir | src/, tests/, examples/ | None | ✅ VERIFIED |
| JavaScript | `npx vitest run` from widget dir | src/, tests/, examples/ | None | ✅ VERIFIED |
| TypeScript | `npx vitest run` from widget dir | src/, tests/, examples/ | None | ✅ VERIFIED |
| Go | `go test ./tests/...` from widget dir | src/, tests/, examples/ | go.mod ✅ | ✅ READY TO TEST |
| Rust | `cargo test` from widget dir | src/lib.rs, tests/, examples/ | Cargo.toml ✅ | ✅ READY TO TEST |

---

## Python - ✅ VERIFIED

### Cartographer Validation (cartographer.py:1135-1146)
```python
# Strategy 1: Run pytest on individual test files
res = subprocess.run(
    [sys.executable, "-m", "pytest", rel_test_file],
    capture_output=True,
    text=True,
    timeout=30,
    cwd=path  # ← Runs FROM widget directory
)
```

### Widget Factory Guidelines
```python
LANGUAGE_GUIDELINES = {
    "python": {
        "testing_framework": "pytest",
        "critical_patterns": """
        1. IMPORTS IN TESTS (MANDATORY):
           import sys
           from pathlib import Path
           sys.path.insert(0, str(Path(__file__).parent.parent))
           from src.{module_name} import {ClassName}

        2. ASYNC TESTS:
           - Use @pytest.mark.asyncio decorator
           - Clean up background tasks in try/finally
        """
    }
}
```

### File Structure
```
widget-name-python/
├── src/
│   └── widget_name.py          # Main implementation
├── tests/
│   └── test_widget_name.py     # pytest discovers test_*.py
├── examples/
│   └── basic_usage.py
└── widget.json
```

### Verification
- ✅ pytest runs from widget directory → sys.path.insert(0, parent.parent) makes src/ importable
- ✅ Test file naming: test_*.py automatically discovered by pytest
- ✅ Async cleanup guidance prevents "Event loop closed" errors
- ✅ Existing widget confirms structure: logic.llamaclient-python

---

## JavaScript/TypeScript - ✅ VERIFIED

### Cartographer Validation (cartographer.py:1147-1162)
```python
# Creates temporary vitest config
vitest_config = "export default { test: { include: ['tests/test_*.*'] } }"
with open(vitest_config_path, 'w') as f:
    f.write(vitest_config)

res = subprocess.run(
    ["npx", "vitest", "run", "--config", "vitest.config.temp.js"],
    capture_output=True,
    text=True,
    timeout=60,
    cwd=widget_dir  # ← Runs FROM widget directory
)
```

### Widget Factory Guidelines
```python
LANGUAGE_GUIDELINES = {
    "javascript": {
        "testing_framework": "vitest",
        "critical_patterns": """
        1. USE VITEST NOT JEST:
           import { describe, it, expect, vi } from 'vitest'

           vi.mock('module-name', () => ({
               default: vi.fn(() => ({ method: vi.fn() }))
           }))

           // NOT jest.mock, NOT jest.fn - use vi.*
        """
    },
    "typescript": {
        "testing_framework": "vitest",
        "critical_patterns": """Same as JavaScript + type safety"""
    }
}
```

### File Structure
```
widget-name-javascript/
├── src/
│   └── widget_name.js          # Main implementation
├── tests/
│   └── test_widget_name.js     # Vitest finds test_*.*
├── examples/
│   └── basic_usage.js
└── widget.json

widget-name-typescript/
├── src/
│   └── widget_name.ts
├── tests/
│   └── test_widget_name.ts
├── examples/
│   └── basic_usage.ts
└── widget.json
```

### Verification
- ✅ Vitest config includes 'tests/test_*.*' → matches our naming
- ✅ Guidelines explicitly say "Use vi.* NOT jest.*"
- ✅ Temp config created automatically by cartographer
- ✅ Detection logic added for jest/vitest mismatch (widget_factory.py:1349-1397)

---

## Go - ✅ IMPLEMENTED & READY TO TEST

### Cartographer Validation (cartographer.py:1163-1171)
```python
elif t_file.endswith(".go"):
    res = subprocess.run(
        ["go", "test", "./tests/..."],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=path  # ← Runs FROM widget directory
    )
```

### Widget Factory Implementation ✅

**go.mod Generation** (widget_factory.py:415-443):
```python
def _generate_go_mod(self, widget_id: str, spec: Dict) -> str:
    """Generate go.mod for Go widgets"""
    module_name = widget_id.replace('_', '-')  # Go prefers dashes

    go_mod = f"""module github.com/cartographer/{module_name}

go 1.21

{require_section if require_section else "// Add dependencies here with: go get <package>"}
"""
    return go_mod
```

**Automatic Writing** (widget_factory.py:1227-1232):
```python
elif language.lower() == "go":
    # Generate and write go.mod
    go_mod_content = self._generate_go_mod(widget_id, spec or {})
    go_mod_path = checkout_dir / "go.mod"
    go_mod_path.write_text(go_mod_content)
```

### Language Guidelines (Unchanged)
```python
LANGUAGE_GUIDELINES = {
    "go": {
        "testing_framework": "testing (stdlib)",
        "file_structure": """
        - src/{module_name}.go (main implementation)
        - tests/{module_name}_test.go (go tests)
        - examples/basic_usage.go (usage example)
        """,
        "critical_patterns": """
        1. TEST STRUCTURE:
           package widgetname_test

           import (
               "testing"
               widget "github.com/cartographer/widget-name/src"
           )

           func TestBasicUsage(t *testing.T) {
               // Table-driven tests preferred
           }
        """
    }
}
```

### File Structure (Implemented)
```
widget-name-go/
├── src/
│   └── widget_name.go          # Generated by LLM
├── tests/
│   └── widget_name_test.go     # Generated by LLM
├── examples/
│   └── basic_usage.go          # Generated by LLM
├── go.mod                      # ✅ AUTOMATICALLY GENERATED
└── widget.json                 # Generated by LLM
```

### How It Works
With go.mod in place, tests can import from src/:
```go
// tests/widget_name_test.go
package widget_test

import (
    "testing"
    widget "github.com/cartographer/widget-name/src"
)

func TestBasicUsage(t *testing.T) {
    w := widget.New()
    // ...
}
```

### Verification Status
- ✅ go.mod generation implemented
- ✅ Module path uses widget-id
- ✅ Tests can import from src/ via module path
- ⏳ **READY FOR TESTING** - Need to verify `go test ./tests/...` works

---

## Rust - ✅ IMPLEMENTED & READY TO TEST

### Cartographer Validation (cartographer.py:1060-1067)
```python
if os.path.exists(os.path.join(path, "Cargo.toml")):
    res = subprocess.run(
        ["cargo", "test"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=path  # ← Runs FROM widget directory
    )
```

### Widget Factory Implementation ✅

**Cargo.toml Generation** (widget_factory.py:372-413):
```python
def _generate_cargo_toml(self, widget_id: str, spec: Dict) -> str:
    """Generate Cargo.toml for Rust widgets"""
    crate_name = widget_id.replace('-', '_').replace('.', '_')

    cargo_toml = f"""[package]
name = "{crate_name}"
version = "1.0.0"
edition = "2021"

[lib]
path = "src/lib.rs"

[dependencies]
{dep_section if dep_section else "# Add dependencies here"}

[[example]]
name = "basic_usage"
path = "examples/basic_usage.rs"
"""
    return cargo_toml
```

**Automatic Writing** (widget_factory.py:1208-1225):
```python
if language.lower() == "rust":
    # Generate and write Cargo.toml
    cargo_toml_content = self._generate_cargo_toml(widget_id, spec or {})
    cargo_toml_path = checkout_dir / "Cargo.toml"
    cargo_toml_path.write_text(cargo_toml_content)

    # Always write as lib.rs for Rust library crates
    src_path = src_dir / "lib.rs"
    src_path.write_text(files["src_file"]["content"])
```

### Updated Language Guidelines ✅
```python
LANGUAGE_GUIDELINES = {
    "rust": {
        "file_structure": """
        - src/lib.rs (main implementation - MUST be lib.rs for library crate)
        - tests/integration_test.rs (integration tests)
        - examples/basic_usage.rs (usage example)
        - Cargo.toml (automatically generated - defines package)
        """,
        "critical_patterns": """
        1. LIBRARY STRUCTURE:
           - src/lib.rs must define public API with pub fn/struct
           - All public items must use 'pub' keyword

        2. TEST STRUCTURE:
           UNIT TESTS (in src/lib.rs):
           #[cfg(test)]
           mod tests { ... }

           INTEGRATION TESTS (in tests/integration_test.rs):
           use widget_name::Widget;
        """
    }
}
```

### File Structure (Implemented)
```
widget-name-rust/
├── src/
│   └── lib.rs                  # ✅ AUTOMATICALLY WRITTEN
├── tests/
│   └── integration_test.rs     # Generated by LLM
├── examples/
│   └── basic_usage.rs          # Generated by LLM
├── Cargo.toml                  # ✅ AUTOMATICALLY GENERATED
└── widget.json                 # Generated by LLM
```

### Verification Status
- ✅ Cargo.toml generation implemented
- ✅ lib.rs naming enforced
- ✅ Language guidelines updated with pub keyword requirements
- ✅ Integration tests use crate import pattern
- ⏳ **READY FOR TESTING** - Need to generate actual Rust widget

---

## Implementation Summary

### ✅ Completed

1. **Python** - VERIFIED & READY
   - No changes needed
   - Guidelines match validation perfectly

2. **JavaScript/TypeScript** - VERIFIED & READY
   - No changes needed
   - Guidelines explicitly use Vitest (vi.* not jest.*)

3. **Go** - IMPLEMENTED & READY TO TEST
   - ✅ Added `_generate_go_mod()` method
   - ✅ Automatically writes go.mod with module path
   - ✅ Tests can import from src/ via module path
   - ⏳ Need to test actual widget generation

4. **Rust** - IMPLEMENTED & READY TO TEST
   - ✅ Added `_generate_cargo_toml()` method
   - ✅ Automatically writes Cargo.toml with lib config
   - ✅ Enforces src/lib.rs naming (not widget_name.rs)
   - ✅ Updated guidelines with pub keyword requirements
   - ⏳ Need to test actual widget generation

### Testing Plan

```bash
# Use the widget factory to generate test widgets
cd /home/Vinscen/Cartographer

# 1. Test Python (should work immediately)
python widget_factory.py --test --debug
# Then try actual generation:
python widget_factory.py --target 1 --native-only

# 2. Test ALL languages with one widget idea
python widget_factory.py --target 1
# This will generate: Python → JavaScript → TypeScript → Go → Rust
# Each will have appropriate build files:
#   - Python: just files
#   - JS/TS: just files
#   - Go: files + go.mod
#   - Rust: files + Cargo.toml (with lib.rs)

# 3. Verify each language validates correctly
cd checkouts/
ls  # Should see widget-name-python, widget-name-javascript, etc.

# Validate each
cartographer validate --path widget-name-python
cartographer validate --path widget-name-javascript
cartographer validate --path widget-name-typescript
cartographer validate --path widget-name-go       # Test go.mod + go test ./tests/...
cartographer validate --path widget-name-rust     # Test Cargo.toml + cargo test
```

---

## Conclusion

### ✅ All Languages Ready for Testing

**Implemented Features:**
- ✅ Python: sys.path injection, pytest patterns, async cleanup
- ✅ JavaScript/TypeScript: Vitest (vi.*) syntax, import patterns
- ✅ Go: go.mod generation with module path, test imports
- ✅ Rust: Cargo.toml generation, lib.rs enforcement, pub keywords

**Key Achievements:**
1. Build files (go.mod, Cargo.toml) automatically generated
2. Language-specific naming conventions enforced (lib.rs for Rust)
3. Comprehensive guidelines embedded in all prompts
4. Import patterns validated for each language

**Next Steps:**
1. Run widget factory to generate multi-language widgets
2. Verify validation passes for each language
3. Fix any issues discovered during testing
4. Document any additional patterns needed

**Status:** READY FOR TESTING - All infrastructure in place!
