# Widget Factory Design

## Your Questions & Answers

### Q: Can we run this all night creating new widgets?
**A: YES!** At 70 T/s, you can realistically generate **150-200+ widgets overnight** (8 hours).

### Q: Should we ensure every widget is its own context window?
**A: YES, for IDEAS.** Each widget idea gets a **fresh context** to ensure creative diversity.

**But NO for implementations** - when implementing the same widget across multiple languages, we **share context** within that widget to maintain consistency.

### Q: If we come up with 1 idea, should we implement it in all languages?
**A: GREAT IDEA!** The factory does exactly this:
1. Generate ONE widget idea
2. Implement in **native language first** (e.g., Python)
3. Then implement in **all other languages** (Go, Rust, TypeScript, etc.)

Same Redis Cache widget → 6 different language implementations!

### Q: Should we share context windows across same widget, different languages?
**A: YES!** When implementing "Redis Cache" in Python vs Go vs Rust:
- All share the same widget **specification**
- Each language gets its own **implementation context**
- But we don't mix languages in the same conversation

### Q: Need command to prevent identical implementations?
**A: Already handled!** Cartographer's `checkin` command has built-in duplicate detection:
- **Exact duplicates**: Blocked automatically
- **Similar code**: Routed to `Pending_Widgets` for review
- **Same widget, different language**: Allowed (uses language suffix like `logic-redis-cache-go`)

## Context Management Strategy

### Fresh Context For:
```python
# Each widget IDEA generation
messages = [
    {"role": "system", "content": brainstorm_prompt},
    {"role": "user", "content": "Propose ONE unique widget"}
]
# ↓ Generate widget spec
# ✅ DUMP CONTEXT
```

### Shared Context For:
```python
# Same widget, same language implementation
messages = [
    {"role": "system", "content": workflow},
    {"role": "user", "content": "Implement Redis Cache in Python"},
    # ↓ Generate files
    {"role": "assistant", "content": "Here are the files..."},
    # ↓ Validation fails
    {"role": "user", "content": "Fix these errors: ..."},
    # ↓ Generate fixes
]
# ✅ DUMP CONTEXT after checkin
```

### Why This Works

**Fresh contexts prevent:**
- ❌ Model getting stuck on similar ideas
- ❌ Repetitive widget suggestions
- ❌ Context contamination across unrelated widgets

**Shared contexts enable:**
- ✅ Error correction with full history
- ✅ Consistent fixes across validation retries
- ✅ Understanding of previous implementation attempts

## Multi-Language Implementation

### How It Works

```
Widget Idea: "Redis Cache Manager"
├── Native Language: Python
│   └── logic-redis-cache (checked in)
│
├── Go Implementation
│   └── logic-redis-cache-go (checked in)
│
├── Rust Implementation
│   └── logic-redis-cache-rust (checked in)
│
├── TypeScript Implementation
│   └── logic-redis-cache-typescript (checked in)
│
└── ... etc
```

### Widget ID Suffixes

- **Native language**: Uses base ID `logic-redis-cache`
- **Other languages**: Appends language `logic-redis-cache-go`

This prevents:
- ❌ ID collisions
- ❌ Duplicate detection false positives
- ✅ Clear language identification

### Cartographer Duplicate Detection

Built into `cartographer checkin`:

```python
# 1. Exact Duplicate (BLOCKED)
if code_hash_matches_existing:
    print("❌ BLOCKED: Exact code already exists")
    exit(1)

# 2. Similar Code (REVIEW)
if similarity_score > threshold:
    print("⚠️  Routed to Pending_Widgets for review")
    # Human reviews in the morning

# 3. Unique (APPROVED)
else:
    print("✅ Successfully registered!")
    # Added to Widget_Library
```

**For cross-language widgets:**
- Same algorithm, different language = **ALLOWED** (code is different)
- Same algorithm, same language = **BLOCKED** (code is identical)

## Overnight Runtime Math

### Per Widget Timing

**Best Case (no retries):**
```
Idea Generation:    10s  (200 input + 500 output tokens)
File Generation:    60s  (1000 input + 3000 output tokens)
Validation:         10s  (subprocess)
Checkin:             5s  (subprocess)
------------------------
Total:              85s per widget
```

**Realistic (1-2 retries):**
```
Idea Generation:    10s
File Generation:    60s
Validation Fail:    30s  (retry 1)
Validation Pass:    10s  (retry 2)
Checkin:             5s
------------------------
Total:             115s per widget
```

### Overnight Projections (8 hours = 28,800 seconds)

**Scenario 1: Native Language Only**
```
28,800s ÷ 115s = 250 widgets (single language)
```

**Scenario 2: Multi-Language (6 languages)**
```
250 widget ideas × 6 languages = 1,500 total implementations
BUT: First implementation is slowest, others are faster
Realistic: 150-200 widget ideas × 6 = 900-1,200 implementations
```

**Scenario 3: Conservative (failures, harder widgets)**
```
200 tokens/s ÷ 70 tokens/s = ~3x slower for complex widgets
150 widget ideas × 6 languages = 900 implementations
```

### What Affects Speed

**Faster:**
- ✅ Simple widgets (cache, validators, utilities)
- ✅ Fewer validation errors
- ✅ Native language implementations
- ✅ Lower retry limits

**Slower:**
- ❌ Complex widgets (ML, crypto, distributed systems)
- ❌ Multiple validation failures
- ❌ Languages with complex setup (Rust, Java)
- ❌ Higher retry limits

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│  Widget Factory (Main Loop)                         │
│                                                      │
│  while count < target:                              │
│    1. Generate Idea (FRESH CONTEXT) ─────────┐      │
│    2. Implement Native Lang (SHARED) ────┐   │      │
│    3. Implement Other Langs (SHARED ea.) │   │      │
│    4. Repeat                             │   │      │
└──────────────────────────────────────────┼───┼──────┘
                                           │   │
                           ┌───────────────┘   │
                           │                   │
                           ▼                   ▼
              ┌────────────────────┐  ┌──────────────┐
              │ Implementation     │  │ Idea Gen     │
              │ (Retry Loop)       │  │ (One-shot)   │
              │                    │  │              │
              │ [Workflow Prompt]  │  │ [Brainstorm] │
              │ [Widget Spec]      │  │ [Library]    │
              │ [Language]         │  │              │
              │                    │  │ ↓            │
              │ ↓                  │  │ Widget Spec  │
              │ Generate Files     │  │ (JSON)       │
              │ ↓                  │  └──────────────┘
              │ Write to Disk      │
              │ ↓                  │
              │ Validate ──┐       │
              │            │       │
              │     Failed │       │
              │            ▼       │
              │    ┌─ Fix Errors   │
              │    │   (LLM)       │
              │    │       │       │
              │    └───────┘       │
              │            │       │
              │     Passed │       │
              │            ▼       │
              │       Checkin      │
              │            │       │
              │            ▼       │
              │       Success!     │
              └────────────────────┘
```

## Testing Before Overnight Run

### 1. Health Check
```bash
./widget_factory.py --health-check
```
**Expected output:**
```
🔍 Checking LLM server health...
✅ LLM server is healthy at http://localhost:8050/v1
📊 Context size: 32768
```

### 2. Idea Generation Test
```bash
./widget_factory.py --test
```
**Expected output:**
```
🧪 TEST MODE: Generating one widget idea...
✅ Successfully generated widget idea:
{
  "widget_id": "logic-jwt-validator",
  "widget_name": "JWT Token Validator",
  ...
}
💡 To implement this widget, run without --test flag
```

### 3. Single Widget Run
```bash
./widget_factory.py --target 1
```
**Expected:**
- Generates 1 widget idea
- Implements in native language
- Validates until success
- Checks in
- Exits

**Takes:** ~2-5 minutes
**Proves:** Full pipeline works end-to-end

### 4. Dry Run (3 widgets)
```bash
./widget_factory.py --target 3
```
**Takes:** ~10-15 minutes
**Proves:**
- Idea diversity (3 different widgets)
- Context is properly reset between widgets
- Logging works correctly

## Configuration Tuning

### For Speed
```python
# widget_factory.py

LANGUAGES = ["python"]  # Only one language
MAX_VALIDATION_RETRIES = 3  # Fail faster

# Lower temperature
temperature=0.2  # More deterministic (faster)
```

### For Quality
```python
LANGUAGES = ["python", "go", "rust", "typescript"]  # Multi-language
MAX_VALIDATION_RETRIES = 10  # More persistent

# Higher temperature for ideas
temperature=0.95  # More creative ideas
```

### For Diversity
```python
# In generate_widget_idea()
temperature=1.0  # Maximum creativity
top_p=0.95  # Nucleus sampling for variety
```

## Monitoring Overnight

### Real-time Log Tail
```bash
# In one terminal: run factory
./widget_factory.py --target 200

# In another: watch logs
tail -f factory_log_*.jsonl | jq -r '.message'
```

### Success Counter
```bash
# Count successful checkins
watch -n 10 'cat factory_log_*.jsonl | jq "select(.level == \"SUCCESS\")" | wc -l'
```

### Search Library Growth
```bash
# Watch library grow
watch -n 30 'cartographer search "" | jq ".library | length"'
```

## What You'll Wake Up To

### Success Scenario (Target: 100)

```
📁 Widget_Library/
   ├── logic-redis-cache/           (Python)
   ├── logic-redis-cache-go/        (Go)
   ├── logic-redis-cache-rust/      (Rust)
   ├── logic-jwt-validator/         (Python)
   ├── logic-jwt-validator-go/      (Go)
   ├── ...                          (90+ more)

📁 checkedin/
   ├── logic-redis-cache_1.0.0_20260110_235000/
   ├── logic-redis-cache-go_1.0.0_20260110_235200/
   ├── ...

📋 factory_log_20260110_230000.jsonl
   ├── 600+ log entries
   ├── 100+ SUCCESS messages
   ├── Widget count: 120

🔍 Library Search
   $ cartographer search ""
   {
     "library": [... 120 widgets ...]
   }
```

### Partial Success Scenario

```
📋 factory_log_*.jsonl
   ├── 80 widgets succeeded
   ├── 15 routed to Pending_Widgets (similar to existing)
   ├── 5 failed after max retries

👉 Action Items:
   - Review Pending_Widgets/
   - Check error logs for failed widgets
   - Re-run factory for 20 more widgets
```

## Failure Recovery

### If Factory Crashes
```bash
# Logs preserve all progress
cat factory_log_*.jsonl | jq 'select(.level == "SUCCESS")' > successful_widgets.json

# Count what was completed
cat successful_widgets.json | jq -s 'length'

# Restart from where it left off
./widget_factory.py --target 50  # Continue generating
```

### If LLM Server Disconnects
Factory will:
1. Detect health check failure
2. Log error
3. Exit gracefully

**Recovery:**
```bash
# Restart LLM server
llama-server -m model.gguf --port 8050

# Restart factory
./widget_factory.py --target <remaining>
```

## Summary

**You asked:** Can I run this overnight and wake up to a massive widget library?

**Answer:** **ABSOLUTELY!**

With proper context management:
- ✅ Fresh contexts for diverse ideas
- ✅ Shared contexts for error recovery
- ✅ Multi-language implementations of each widget
- ✅ Built-in duplicate detection
- ✅ Retry logic for validation failures
- ✅ 150-200+ widgets overnight at 70 T/s

Just run:
```bash
./test_factory.sh           # Pre-flight check
./widget_factory.py --test  # Verify idea generation
./widget_factory.py --target 1  # Test full pipeline
./widget_factory.py --target 200  # Go to bed!
```

Wake up to hundreds of production-ready widgets! 🚀
