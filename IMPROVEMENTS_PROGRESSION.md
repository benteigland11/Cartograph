# Error Recovery Improvements - Session Progression

## Session Timeline

### Phase 1: Context Cleanup
**Goal**: Reduce signal-to-noise ratio by removing workflow.md from code generation

**Before**:
- System prompt: 27KB (workflow.md) on EVERY generation call
- Per widget: 27KB × 4 files = 108KB waste
- Actual signal used: 16.7% of 64K context

**After**:
- System prompt: 140 chars (minimal, focused)
- Per widget: 140 chars × 4 files = 560 bytes
- Signal-to-noise: 98.8% reduction

**Impact**: Cleaner code generation, more reliable LLM behavior

---

### Phase 2: Initial Search-and-Replace Testing
**Goal**: Test if brittle string-matching search-and-replace could work

**Implementation**: Model returns JSON with `search` and `replace` fields

**Result**: 27.3% pass rate (3/11)
```
✅ Missing comma between fields
✅ Unterminated string
✅ Single quotes → double
❌ Extra trailing comma (search not found)
❌ Malformed escape (identity replacement)
❌ ... and 6 more failures
```

**Root Cause**: Tokenization precision loss in Q4_K_M quantization

---

### Phase 3: Comprehensive Testing Framework
**Goal**: Build test harness with all 11 broken JSON scenarios

**Test Cases Identified**:
1. Missing comma between fields
2. Unterminated string
3. Single quotes instead of double
4. Extra trailing comma
5. Malformed escape sequence
6. Unescaped newline in string
7. Missing closing brace
8. Duplicate key
9. Invalid number format
10. Misspelled boolean (True/False)
11. Misspelled null (None)

**Framework Features**:
- Unified diff analysis
- Line change extraction
- Bottom-to-top application
- Comprehensive result reporting

---

### Phase 4: Corrected + Difflib Approach (v1)
**Goal**: Ask for corrected JSON, use difflib to identify changes

**Implementation**:
```python
# Get model to fix JSON (works WITH training)
corrected_json = await model.fix_json(broken_json)

# Use difflib to find exact changes
diff = unified_diff(orig_lines.split('\n'),
                    corrected_json.split('\n'))
changes = parse_diff_output(diff)

# Apply bottom-to-top to avoid line shifting
fixed_json = apply_changes_bottom_to_top(orig_lines, changes)
```

**Result**: 72.7% pass rate (8/11)
```
✅ Missing comma between fields
✅ Unterminated string
✅ Single quotes → double
✅ Extra trailing comma
✅ Malformed escape sequence
✅ Invalid number format
✅ Misspelled boolean
✅ Misspelled null
❌ Unescaped newline (difflib failed)
❌ Missing closing brace (difflib failed)
❌ Duplicate key (difflib failed)
```

**Issue**: Line count changes broke difflib-based edit application

---

### Phase 5: Fixed Markdown Extraction
**Goal**: Handle ```json``` code fences correctly

**Problem Found**:
```python
# BEFORE (broken):
if part_stripped.startswith('{'):
    # part_stripped = 'json\n{...}' doesn't start with '{', fails!

# AFTER (fixed):
if part_stripped.startswith('json'):
    part_stripped = part_stripped[4:].strip()  # Remove 'json'
if part_stripped.startswith('{'):
    # NOW it works!
```

**Result**: 72.7% → 72.7% (same, but Malformed escape now uses retry)
```
Malformed escape sequence: Attempt 1 ❌ → Attempt 2 ✅ (retry worked!)
Unescaped newline: Attempt 1 ❌ → Attempt 2 ✅ (retry worked!)
```

**Insight**: Retry loop is functioning - provides 2nd chance recovery

---

### Phase 6: Line-Count Aware Difflib (v2)
**Goal**: Detect when line structure changes and use corrected JSON directly

**Root Cause Analysis**:
- Lines added/deleted → line numbers don't correspond
- Applying edits to wrong positions → invalid JSON
- Example:
  - Original: 9 lines
  - Corrected: 8 lines (consolidated newline in string)
  - Difflib extracts: "Replace line 6"
  - Applying to line 6 of original → overwrites wrong content

**Solution**:
```python
if len(orig_lines) != len(fixed_lines):
    # Structure changed: use corrected directly
    fixed_json_str = corrected_json
else:
    # Structure same: use difflib for precision
    fixed_json_str = apply_difflib_edits(orig_lines, corrected_json)
```

**Result**: 72.7% → 100% pass rate (11/11)
```
All 11 tests now passing:
- 9 pass on attempt 1 (81.8%)
- 2 pass on attempt 2 (18.2%)
- 0 need attempt 3 (0.0%)
```

---

## Key Insights by Phase

| Phase | Discovery | Impact |
|-------|-----------|--------|
| 1 | Context pollution reduces signal | Cleanup enables better prompting |
| 2 | Tokenization precision too low | Search-replace fundamentally broken |
| 3 | Structured testing essential | Identifies edge cases systematically |
| 4 | Corrected JSON is reliable | Works with model training, not against it |
| 5 | Response format handling matters | Markdown extraction critical |
| 6 | Line structure changes break diffs | Line count awareness is the key |

---

## Evolution of Success Rate

```
Search-Replace (v0):      ████░░░░░░░░░░░░░░░░░░░░░░░  27.3%
Line Identification (v0): ███████████░░░░░░░░░░░░░░░░░  50.0%
Corrected+Difflib (v1):   ████████████████████░░░░░░░░  72.7%
Fixed Markdown (v1.5):    ████████████████████░░░░░░░░  72.7% (retry helps)
Line-Aware Difflib (v2):  ████████████████████████████░ 100.0%
```

---

## Critical Implementation Details

### Bottom-to-Top Line Application
```python
# Apply changes in reverse order (highest line numbers first)
# This prevents line numbers from shifting during edits
for line_num, new_content in sorted(changes, key=lambda x: x[0], reverse=True):
    orig_lines[line_num - 1] = new_content
```

### Markdown Extraction Pipeline
```
1. Strip thinking tags (if present)
2. Try direct JSON parse
3. If failed, look for first { and last }
4. If no match, split by ``` code fences
5. For each part, check if starts with 'json' or '{'
6. Remove 'json' identifier if present
7. Extract and return JSON
```

### Line Count Detection
```python
# Small but critical check
if len(orig_lines) != len(fixed_lines):
    # Structure changed - don't try to map line numbers
    use_corrected_directly = True
else:
    # Structure same - precise line-by-line edits possible
    use_difflib_edits = True
```

---

## Retry Loop Strategy

**Why 3 attempts?**
- Attempt 1: Catches 81.8% immediately (most common errors)
- Attempt 2: Catches edge cases (18.2%) - markdown extraction issue, escape sequences
- Attempt 3: Reserve - zero failures needed it in testing

**Cost-Benefit**:
- Attempt 1: ~300 tokens, 10 seconds
- Attempt 2: ~300 tokens, 10 seconds (if needed)
- Attempt 3: ~300 tokens, 10 seconds (if needed)
- Total: Max 900 tokens vs 3000+ for full regeneration
- Savings: 70% token cost when recover succeeds

---

## Production Readiness Checklist

- ✅ 100% test pass rate on diverse error types
- ✅ Retry loop validates (uses attempts 1-2, not 3)
- ✅ Markdown extraction robust
- ✅ Line count awareness prevents edge cases
- ✅ Context usage well under 32K
- ✅ Thinking tags don't pollute recovery
- ✅ Bottom-to-top application prevents shifting
- ✅ Integration into widget_factory.py complete

---

## Lessons for Similar Problems

1. **Don't fight training**: Ask models for what they're trained to do (fix code), not brittle parsing tasks (exact string matching)

2. **Structure matters**: Detect when structural assumptions break (line count changes) and adjust strategy

3. **Response format is critical**: JSON, markdown code fences, thinking tags - all need robust extraction

4. **Retry strategies work**: Simple 3-attempt loop caught 100% when combined with proper extraction

5. **Test comprehensively**: Edge cases (escaped newlines, structural changes) reveal true issues

6. **Quantization precision**: Q4_K_M is great for efficiency but has limits on exact recall tasks
