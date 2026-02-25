# Widget Creation Workflow - Coding Agent Instructions

You are a coding agent tasked with creating a production-ready widget for Cartographer. You will follow the checkout → implement → validate → checkin workflow to ensure quality standards are met.

## Prerequisites

You should have received:
1. **Widget specification** (from brainstorming phase) - JSON with widget details
2. **Cartographer path** - Location of cartographer.py script
3. **Working directory** - Where to perform checkout

## Workflow Overview

```
1. Checkout → Create isolated workspace
2. Implement → Write widget code (src/, tests/, examples/)
3. Validate → Run quality checks and tests
4. Fix → Address any validation failures
5. Checkin → Submit to library
```

## Step 1: Checkout (Create Workspace)

### For New Widgets

```bash
python /path/to/cartographer.py checkout <widget-id> --new --name "<Widget Name>" --type widget
```

**Example:**
```bash
python /home/Vinscen/Cartographer/cartographer.py checkout logic-redis-cache --new --name "Redis Cache Manager" --type widget
```

**Result:** Creates `./checkouts/<widget-id>/` with boilerplate structure:
- `widget.json` (manifest with [TODO] placeholders)
- `src/` (empty directory)
- `tests/` (empty directory)
- `examples/` (empty directory)
- `README_CHECKOUT.md` (workflow instructions)

### For Editing Existing Widgets

```bash
python /path/to/cartographer.py checkout <widget-id>
```

**Result:** Creates `./checkouts/<widget-id>/` with existing widget code, version auto-incremented.

## Step 2: Implement Widget

Navigate to checkout directory and create all required files:

```bash
cd ./checkouts/<widget-id>/
```

### File 1: widget.json (Manifest)

**CRITICAL:** Replace ALL [TODO] placeholders with actual values.

```json
{
  "meta": {
    "id": "logic-redis-cache",
    "name": "Redis Cache Manager",
    "version": "1.0.0",
    "type": "widget",
    "domain": "backend",
    "tags": ["cache", "redis", "storage", "performance"],
    "maturity": "beta"
  },
  "description": "Production-ready Redis caching layer with automatic serialization, TTL management, and graceful degradation.",
  "tech_stack": {
    "language": "python",
    "language_version": ">=3.8",
    "dependencies": ["redis", "asyncio"]
  },
  "integration_guide": {
    "usage": "Import RedisCache, initialize with redis_url and optional namespace, then use get/set/delete methods.",
    "constraints": "Requires Redis server running. Falls back gracefully if Redis is unavailable."
  },
  "depends_on": []
}
```

**Validation checklist:**
- [ ] No [TODO] placeholders remain
- [ ] All required fields filled: id, name, version, type, domain, tags
- [ ] Description is clear and specific
- [ ] Dependencies list is complete
- [ ] integration_guide.usage explains how to use
- [ ] integration_guide.constraints lists requirements

### File 2: src/<implementation>

Create implementation file(s) in `src/` directory.

**Python example:** `src/redis_cache.py`
**Go example:** `src/redis_cache.go`
**Rust example:** `src/lib.rs`
**TypeScript example:** `src/RedisCache.ts`

**Requirements:**
- ✅ Constructor accepts ALL dependencies (no hard-coded config)
- ✅ Type hints/annotations where applicable
- ✅ Comprehensive docstrings/comments
- ✅ Error handling with custom exceptions/errors
- ✅ Async/await for I/O operations (if applicable)

### File 3: tests/test_<name>

Create test file in `tests/` directory.

**Python:** `tests/test_redis_cache.py`
**Go:** `tests/redis_cache_test.go`
**Rust:** `tests/redis_cache_test.rs` or in `src/lib.rs` with `#[cfg(test)]`
**TypeScript:** `tests/RedisCache.test.ts`

**Requirements:**
- ✅ Test all core methods
- ✅ Test error handling
- ✅ Test edge cases
- ✅ Use mocks for external dependencies (Redis, APIs, etc.)
- ✅ All tests MUST pass

**Example test structure:**
```python
def test_basic_get_set():
    # Test basic functionality
    pass

def test_error_handling():
    # Test failure scenarios
    pass

def test_edge_cases():
    # Test null values, empty inputs, etc.
    pass
```

### File 4: examples/basic_usage.<ext>

Create executable example in `examples/` directory.

**Python:** `examples/basic_usage.py`
**Go:** `examples/basic_usage.go`
**Other:** Use appropriate extension

**Requirements:**
- ✅ Runnable code (not markdown)
- ✅ Imports widget from `../src/`
- ✅ Shows realistic usage
- ✅ Includes comments
- ✅ Can be executed: `python examples/basic_usage.py`

## Step 3: Validate

Run validation to check if widget meets quality standards:

```bash
python /path/to/cartographer.py validate --path ./checkouts/<widget-id>
```

### Validation Checks

The validator will check:

1. ✅ Path exists
2. ✅ widget.json exists and is valid JSON
3. ✅ No [TODO] placeholders in widget.json
4. ✅ src/ folder exists and has files
5. ✅ tests/ folder exists and has files
6. ✅ examples/ folder exists and has files
7. ✅ Required meta fields present (id, name, domain)
8. ✅ Tech stack fields present (for widgets)
9. ✅ Integration guide fields present
10. ✅ depends_on array present
11. ✅ Test files follow naming convention (test_*.*)
12. ✅ **All tests pass**
13. ✅ Maturity level is appropriate
14. ✅ Implementation is unique (no duplicate code)

### Reading Validation Output

**Success:**
```
============================================================
✅ VALIDATION PASSED
============================================================
  ✅ Path exists
  ✅ widget.json exists
  ✅ widget.json is valid JSON
  ...
  ✅ All tests pass
============================================================
```

**Failure:**
```
============================================================
❌ VALIDATION FAILED
============================================================
  ✅ Path exists
  ✅ widget.json exists
  ❌ No [TODO] placeholders in widget.json
  ...
------------------------------------------------------------
ERRORS:
  1. Found 3 [TODO] tag(s) - replace all placeholders
------------------------------------------------------------
```

## Step 4: Fix Validation Failures

If validation fails, address each error:

### Common Failures & Fixes

**1. [TODO] placeholders in widget.json**
- Find all [TODO] in widget.json
- Replace with actual values
- Re-run validation

**2. Missing files in src/ or tests/ or examples/**
- Create required files
- Ensure directories are not empty
- Re-run validation

**3. Tests failing**
```
ERRORS:
  1. Test 'test_basic_usage' failed

TEST OUTPUT:
AssertionError: expected 'foo' but got 'bar'
```

**Fix:**
- Read test output carefully
- Fix implementation or test
- Run tests locally: `python -m pytest tests/`
- Re-run validation

**4. Missing required fields**
```
ERRORS:
  1. Missing required field(s): domain
```

**Fix:**
- Add missing field to widget.json meta section
- Re-run validation

**5. Test files don't follow naming convention**
```
ERRORS:
  1. No test files found matching test_*.py or test_*.js pattern
```

**Fix:**
- Rename test file to `test_<name>.<ext>`
- Re-run validation

### Iteration Loop

```bash
# Fix issues
vim ./checkouts/<widget-id>/widget.json
vim ./checkouts/<widget-id>/src/implementation.py
vim ./checkouts/<widget-id>/tests/test_implementation.py

# Re-validate
python /path/to/cartographer.py validate --path ./checkouts/<widget-id>

# Repeat until validation passes
```

## Step 5: Checkin

Once validation passes, submit widget to library:

```bash
python /path/to/cartographer.py checkin ./checkouts/<widget-id> --reason "Initial implementation of Redis caching layer"
```

### Checkin Process

**What happens:**
1. Final validation run
2. Duplicate detection (checks if similar widgets exist)
3. Widget moved to Widget_Library/
4. Checkout directory archived to `./checkedin/` with timestamp
5. Widget becomes searchable in library

### Checkin Output

**Success:**
```
============================================================
✅ VALIDATION PASSED
============================================================
  ✅ All checks pass
============================================================

✅ Successfully registered logic-redis-cache!
🚀 Added directly to Widget_Library
```

**Duplicate Warning (needs review):**
```
🔍 Checking for duplicates in widgets...
⚠️  Routed to Pending_Widgets for review (similarity found)
```

**Blocked (exact duplicate):**
```
❌ BLOCKED: Exact code implementation already exists in logic-existing-cache
```

### After Successful Checkin

Your widget is now:
- ✅ In the Widget_Library/
- ✅ Searchable: `python cartographer.py search "redis cache"`
- ✅ Installable: `python cartographer.py install logic-redis-cache`
- ✅ Checkout archived to `./checkedin/<widget-id>_<version>_<timestamp>/`

## Complete Example Workflow

```bash
# 1. Checkout (create workspace)
python /home/Vinscen/Cartographer/cartographer.py checkout logic-redis-cache --new --name "Redis Cache Manager" --type widget

# 2. Implement files
cd ./checkouts/logic-redis-cache/

# Edit widget.json (remove [TODO] placeholders)
vim widget.json

# Create implementation
cat > src/redis_cache.py << 'EOF'
"""Redis caching layer with automatic serialization."""
import redis
import json

class RedisCache:
    def __init__(self, redis_url: str, namespace: str = ""):
        self.client = redis.from_url(redis_url)
        self.namespace = namespace

    def get(self, key: str):
        full_key = f"{self.namespace}:{key}" if self.namespace else key
        value = self.client.get(full_key)
        return json.loads(value) if value else None

    def set(self, key: str, value, ttl: int = 3600):
        full_key = f"{self.namespace}:{key}" if self.namespace else key
        self.client.setex(full_key, ttl, json.dumps(value))
EOF

# Create tests
cat > tests/test_redis_cache.py << 'EOF'
from unittest.mock import Mock, patch
from src.redis_cache import RedisCache

@patch('redis.from_url')
def test_basic_get_set(mock_redis):
    mock_client = Mock()
    mock_redis.return_value = mock_client

    cache = RedisCache("redis://localhost")
    cache.set("key1", "value1")

    mock_client.setex.assert_called_once()
EOF

# Create examples
cat > examples/basic_usage.py << 'EOF'
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from src.redis_cache import RedisCache

def main():
    cache = RedisCache("redis://localhost:6379", namespace="myapp")
    cache.set("user:123", {"name": "Alice"}, ttl=600)
    user = cache.get("user:123")
    print(f"User: {user}")

if __name__ == "__main__":
    main()
EOF

# 3. Validate
cd ../..
python /home/Vinscen/Cartographer/cartographer.py validate --path ./checkouts/logic-redis-cache

# 4. Fix any issues (repeat validate until it passes)
# ... edit files as needed ...

# 5. Checkin
python /home/Vinscen/Cartographer/cartographer.py checkin ./checkouts/logic-redis-cache --reason "Initial implementation with TTL support and namespace isolation"

# 6. Verify it's in library
python /home/Vinscen/Cartographer/cartographer.py search "redis cache"
```

## Error Recovery

### Validation keeps failing
- Read error messages carefully
- Fix ONE issue at a time
- Re-run validation after each fix
- Check TEST OUTPUT section for test failures

### Checkin blocked by duplicate
- Read similarity report
- If truly different, use `--differentiation` flag:
  ```bash
  python cartographer.py checkin ./checkouts/<id> \
    --reason "..." \
    --differentiation "My widget handles distributed caching while existing widgets are single-instance only"
  ```

### Need to start over
```bash
# Remove failed checkout
rm -rf ./checkouts/<widget-id>

# Start fresh
python cartographer.py checkout <widget-id> --new --name "..." --type widget
```

## Success Criteria

Your widget is complete when:
- ✅ Validation passes with all green checkmarks
- ✅ Checkin succeeds without errors
- ✅ Widget appears in library search results
- ✅ Widget can be installed: `python cartographer.py install <widget-id>`
- ✅ Checkout directory is archived in `./checkedin/`

## Tips for Success

1. **Read validation errors carefully** - They tell you exactly what to fix
2. **Fix one error at a time** - Don't try to fix everything at once
3. **Run tests locally** - Before validation, run `pytest tests/` to catch failures early
4. **Keep it simple** - Simple, focused widgets are better than complex ones
5. **Follow language conventions** - Use idiomatic code for the language
6. **Test with mocks** - Don't require external services (Redis, APIs) to run tests
7. **Make examples runnable** - Examples should execute without errors

Now proceed with widget implementation!
