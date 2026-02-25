# Overnight Widget Factory

Autonomous widget generation using your local Nemotron LLM running at 70 T/s.

## What It Does

1. **Generates widget ideas** using fresh LLM context each time
2. **Implements widgets** following your validated workflow
3. **Validates automatically** and retries with error feedback until success
4. **Checks in to library** when validation passes
5. **Repeats** until target count reached or you stop it

## Quick Start

### Prerequisites

1. **LLM Server Running**: Your Nemotron model on port 8050
   ```bash
   # Make sure llama-server is running on port 8050
   # Check with: curl http://localhost:8050/v1/models
   ```

2. **Cartographer Available**: `cartographer` command in PATH
   ```bash
   cartographer --help  # Should work
   ```

### Run Overnight

```bash
# Default: Generate 100 widgets
./widget_factory.py

# Custom target
./widget_factory.py --target 200

# Custom LLM port
./widget_factory.py --url "http://localhost:8080/v1"

# Specific languages only
./widget_factory.py --languages python go rust
```

### In Background (Screen/Tmux)

```bash
# Using screen
screen -S widget_factory
./widget_factory.py --target 150
# Ctrl+A, D to detach

# Check progress
screen -r widget_factory

# Or using tmux
tmux new -s widgets
./widget_factory.py
# Ctrl+B, D to detach
tmux attach -t widgets
```

### Overnight Run

```bash
# Start before bed
nohup ./widget_factory.py --target 200 > factory_output.log 2>&1 &

# Check in the morning
tail -f factory_output.log

# Or check JSON log
tail -f factory_log_*.jsonl | jq
```

## How It Works

### Context Management

- **Fresh context per widget idea**: Each brainstorming session starts clean
- **Shared context per widget+language**: When implementing Redis cache in Python vs Go, each language gets its own context
- **No context stacking**: After checkin, context is dumped before next widget

### Workflow

```
┌─────────────────────────────────────┐
│  Generate Widget Idea (Fresh)       │
│  - Reads brainstorm prompt          │
│  - Checks existing library          │
│  - Creates unique spec              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Implement in Native Language       │
│  - Checkout workspace               │
│  - Generate all files               │
│  - Validate ──┐                     │
│               │ Failed              │
│               ├─► Fix & Retry (5x)  │
│               │                     │
│  - Checkin ◄──┘ Passed              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Implement in Other Languages       │
│  (Optional - Same process)          │
└─────────────────────────────────────┘
```

### Multi-Language Strategy

For each widget idea, the factory:
1. Implements in **native language first** (specified in spec)
2. If successful, implements in **all other languages**
3. Each language gets same widget spec but language-specific code

Example:
- Idea: "Redis Cache Manager" (native: Python)
- Generates: `logic-redis-cache` (Python)
- Generates: `logic-redis-cache-go` (Go)
- Generates: `logic-redis-cache-rust` (Rust)
- etc.

### Retry Logic

If validation fails:
1. Captures error output from `cartographer validate`
2. Feeds errors back to LLM
3. LLM generates fixes
4. Writes fixed files
5. Validates again
6. Repeats up to 5 times

If still failing after 5 retries: **Skips to next widget** (no infinite loops)

## Monitoring

### Log Files

Two log files are created:

1. **JSONL Log**: `factory_log_YYYYMMDD_HHMMSS.jsonl`
   ```bash
   # Watch in real-time with jq
   tail -f factory_log_*.jsonl | jq -r '.message'

   # Count successes
   cat factory_log_*.jsonl | jq 'select(.level == "SUCCESS")' | wc -l

   # See errors
   cat factory_log_*.jsonl | jq 'select(.level == "ERROR")'
   ```

2. **Stdout** (if running in foreground or with `tee`)

### Progress Indicators

```
📝 INFO    - Regular messages
✅ SUCCESS - Widget checked in!
❌ ERROR   - Something failed
⚠️  WARN   - Validation failed, retrying
```

## Configuration

Edit top of `widget_factory.py`:

```python
LLAMA_URL = "http://localhost:8050/v1"  # Your LLM server
LANGUAGES = ["python", "go", "rust", "typescript", "javascript", "java"]
MAX_VALIDATION_RETRIES = 5  # How many fix attempts
TARGET_WIDGET_COUNT = 100   # Default target
```

## Stopping

```bash
# Graceful stop (if running in foreground)
Ctrl+C

# Kill background process
pkill -f widget_factory.py

# Or find PID from nohup/screen and kill
```

## Expected Throughput

At **70 T/s** with your Nemotron model:

- **Widget idea**: ~200 tokens input + ~500 output = ~10 seconds
- **Implementation**: ~1000 tokens input + ~3000 output = ~60 seconds
- **Fixes (if needed)**: ~30 seconds per retry
- **Validation + Checkin**: ~10 seconds

**Best case**: ~80 seconds per widget
**Realistic**: ~120 seconds per widget (with some retries)

**Overnight (8 hours)**:
- Best case: ~360 widgets
- Realistic: ~240 widgets
- Conservative: **150+ widgets** (accounting for harder problems)

## Tweaking for Performance

### To Generate MORE Widgets

1. **Only native language** (skip cross-language implementations):
   ```python
   # In run_overnight(), comment out the "Phase 3" loop
   ```

2. **Lower retry limit**:
   ```python
   MAX_VALIDATION_RETRIES = 3  # Fail faster
   ```

3. **Parallel generation** (if you have GPU memory):
   - Run multiple factory instances with different targets
   - Each gets fresh LLM requests (stateless)

### To Generate BETTER Widgets

1. **More retries**:
   ```python
   MAX_VALIDATION_RETRIES = 10  # More persistent
   ```

2. **Lower temperature for code**:
   ```python
   # In implement_widget_files()
   temperature=0.1  # More deterministic
   ```

3. **Manual review step**:
   - Route to `Pending_Widgets` instead of direct checkin
   - Review in the morning before accepting

## Troubleshooting

### "LLM server not available"
```bash
# Check if llama-server is running
curl http://localhost:8050/v1/models

# Start it if needed
llama-server -m /path/to/model.gguf --port 8050
```

### "Cartographer command not found"
```bash
# Add to PATH or use absolute path
export PATH="$PATH:/path/to/cartographer/bin"
```

### Too many validation failures
- Check the error logs
- Some widget types might be harder (e.g., Rust requires more setup)
- Consider excluding difficult languages initially

### Duplicate widgets
- Factory checks existing library before generating ideas
- Cartographer's duplicate detection will catch similar implementations
- May route to `Pending_Widgets` for review

## Wake Up To

In the morning, you'll have:
- ✅ **100+ widgets** in your library (if running at target 100)
- 📋 **Detailed logs** showing what was generated
- 📁 **Checkedin archives** of all successful widgets
- 🔍 **Searchable library**: `cartographer search <keyword>`

## Example Session

```bash
$ ./widget_factory.py --target 50

📝 [2026-01-10T23:00:00] 🚀 Widget Factory Started - Target: 50 widgets
📝 [2026-01-10T23:00:00] 📡 LLM Server: http://localhost:8050/v1
📝 [2026-01-10T23:00:00] 🔧 Languages: python, go, rust, typescript, javascript, java
✅ [2026-01-10T23:00:01] ✅ LLM server healthy

============================================================
Progress: 0/50 widgets
============================================================

📝 [2026-01-10T23:00:05] Generating new widget idea...
📝 [2026-01-10T23:00:12] Generated idea: logic-jwt-validator
📝 [2026-01-10T23:00:12] Starting implementation: logic-jwt-validator
📝 [2026-01-10T23:00:13] Generating code for logic-jwt-validator in python...
📝 [2026-01-10T23:01:45] Validation attempt 1/5
✅ [2026-01-10T23:01:50] Validation passed!
✅ [2026-01-10T23:02:00] Successfully checked in logic-jwt-validator!
📝 [2026-01-10T23:02:00] Implementing logic-jwt-validator in go...
...
```

Now go to bed and wake up to a massive widget library!
