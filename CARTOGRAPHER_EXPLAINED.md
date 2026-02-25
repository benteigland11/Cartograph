# Cartographer: An AI-Native Package Manager

## The Core Idea

Cartographer is a package manager designed specifically for AI coding assistants. Unlike traditional package managers built for humans, it treats AI as a first-class user by outputting strict JSON, providing code examples as documentation, and handling file operations automatically.

**Philosophy:** "Reuse battle-tested code first; write custom code second"

**The Problem It Solves:** AI assistants constantly regenerate the same utilities, components, and patterns because they don't have a reliable way to discover and reuse existing code. This creates duplicate implementations, inconsistent quality, and wasted effort.

**The Solution:** A growing library of widgets (reusable components) and blueprints (architectural patterns) that AI agents can search, evaluate, install, and integrate autonomously.

## Core Concepts

### Widgets

Reusable code components with a standardized structure:

```
Widget_Directory/
├── widget.json          # Manifest with metadata, dependencies, integration guide
├── src/                 # Implementation code
├── tests/              # Test suite (required for quality)
├── examples/           # Usage examples (the AI's "documentation")
├── reviews.json        # Community ratings
└── history/            # Version history
```

**Key Innovation:** The `examples/basic_usage.*` file serves as the contract between library and AI. Instead of parsing docs, the AI reads executable examples showing exact usage.

**Naming Convention:** `category.name-language` (e.g., `logic.rate-limiter-python`, `ui.chat-panel-javascript`)

**Maturity Levels:** Prototype → Beta → Stable → Deprecated

### Blueprints

Higher-level architectural patterns that compose multiple widgets:

```json
{
  "name": "Workflow.Authentication",
  "composed_of": [
    "logic-cognitoauth",
    "logic-pkce-utils",
    "logic-authentication-service"
  ],
  "integration_guide": {
    "pattern": "dependency_injection",
    "wiring_steps": [...]
  }
}
```

Blueprints encode proven architectural patterns so teams don't reinvent auth flows, chat systems, or ETL pipelines.

### Dark Matter

Code that exists in project source but should be in the library. This is the Gardener agent's target - complex glue code, repeated patterns, or standalone utilities that deserve to be extracted and shared.

## The Agent Triad

Cartographer introduces a three-role pattern for AI development:

### 1. Explorer Agent (Supply Chain / Architect)

**Prime Directive:** "Measure Twice, Code Once"

**Responsibilities:**
- Maps user requirements into vertical slices (UI + Logic + Data)
- Searches library for matching widgets
- Performs parallel feasibility probes
- Evaluates complexity (LoC), dependencies, maturity
- Provisions chosen widgets into project

**Commands:** `search`, `inspect --all`, `install`, `uninstall`

**Workflow:**
```
User: "Add real-time chat"
Explorer:
  → Search: "chat panel", "websocket", "message store"
  → Inspect candidates for quality, dependencies
  → Install: ui-chat-panel, logic-websocket-client, logic-sqlite-message-store
```

### 2. Builder Agent (Feature Assembler)

**Prime Directive:** "Don't Reinvent the Wheel"

**Responsibilities:**
- Reads `examples/basic_usage.*` to understand widget APIs
- Writes "glue code" to connect widgets
- Never reimplements generic infrastructure
- Rates widgets after use to improve library quality

**Commands:** IDE tools, `rate`

**Workflow:**
```
Builder:
  → Read examples/basic_usage.js for each installed widget
  → Write integration code in src/features/chat.js
  → Rate widgets: cartographer rate ./cartographer/widgets/ui-chat-panel --score 5
```

### 3. Gardener Agent (Library Evolution / Refactoring)

**Prime Directive:** "Standardize the Patterns"

**Responsibilities:**
- Identifies "Dark Matter" (code that should be widgets)
- Extracts patterns from project code
- Upgrades existing widgets based on feedback
- Refactors project to use new library assets

**Commands:** `checkout`, `validate`, `checkin`

**Workflow:**
```
Gardener:
  → Notice complex glue code connecting 3 widgets
  → Extract pattern into new blueprint: Workflow.RealtimeChat
  → Refactor project to use blueprint
  → Library now has reusable chat workflow
```

## The Development Cycle

```
User Request → Explorer → Builder → Gardener → (Library Grows)
     ↓            ↓          ↓          ↓
  "Feature"   Provision  Assemble   Extract
              Widgets    + Glue     Patterns
                         Code      → Library
```

**Key Insight:** This creates a self-improving ecosystem. As teams build features, the Gardener extracts reusable patterns back into the library, making future development faster.

## Key Design Principles

### 1. AI-Native Design

**JSON-First Output:** All commands output strict JSON to prevent AI hallucination
```bash
cartographer search "rate limiter" --format json
# Returns parseable JSON, never prose
```

**Examples as Documentation:** AI reads executable code, not written docs
```python
# examples/basic_usage.py shows exact usage
from src.redis_cache import RedisCache
cache = RedisCache(redis_url="redis://localhost", namespace="app")
cache.set("key", "value", ttl=3600)
```

**Automatic File Operations:** Install directly modifies project files, no manual copy/paste

### 2. Quality Assurance

**Duplicate Detection:** Implementation hash comparison prevents redundant widgets
```bash
cartographer checkout logic-redis-cache --new
# If implementation already exists, CLI warns and suggests existing widget
```

**Proof of Use for Ratings:** Must provide path to installed widget
```bash
# Prevents fake reviews
cartographer rate ./cartographer/widgets/logic.rate-limiter --score 5
```

**Required Tests:** Validation fails without passing tests
```bash
cartographer validate --path ./checkouts/my-widget
# ✅ Tests must exist and pass
```

### 3. Dependency Injection over Configuration

Widgets accept dependencies as constructor parameters, never hardcode config:
```python
# Good - flexible, testable
cache = RedisCache(redis_url="...", namespace="myapp")

# Bad - hardcoded
cache = RedisCache()  # assumes localhost:6379
```

### 4. The Golden Rule

"NEVER manually edit code inside the `cartographer/` directory"

**Two Integration Strategies:**
- **Reference:** Import widgets directly (keeps library updates)
- **Template:** Copy to project and customize (fork from library)

## Technical Implementation

### Search Engine

BM25-based search with:
- Synonym expansion (e.g., "cache" → "memoization", "storage")
- Tag boosting (exact tag matches ranked higher)
- Code indexing (searches actual implementations, not just metadata)

### Version Management

- Full version history in `history/` directory
- Rollback capability
- Version-specific ratings to detect regressions

### Installation Statistics

Tracks widget popularity to surface trusted components:
```bash
cartographer popular
# Shows most-installed widgets as quality signal
```

## The Contribution Workflow

```bash
# 1. Checkout workspace
cartographer checkout logic-redis-cache --new --name "Redis Cache"

# 2. Implement
cd checkouts/logic-redis-cache/
# - Edit widget.json (remove [TODO] placeholders)
# - Create src/redis_cache.py
# - Create tests/test_redis_cache.py
# - Create examples/basic_usage.py

# 3. Validate (runs tests, checks manifest)
cartographer validate --path ./checkouts/logic-redis-cache

# 4. Checkin (moves to library)
cartographer checkin ./checkouts/logic-redis-cache --reason "Initial implementation"
```

**Validation Checks:**
- No `[TODO]` placeholders in manifest
- All required fields present
- Source files exist
- Tests exist and pass
- Examples are runnable
- No duplicate implementations

## Current State (January 2026)

**Library Health:**
- 57 total items (46 widgets, 11 blueprints)
- 52% test coverage
- 66% have basic_usage examples
- 100% have maturity levels assigned

**Completed Phases:**
- ✅ Phase 1: Foundation (validation, maturity tracking)
- ✅ Phase 2: Widget extraction with duplicate detection
- ✅ Phase 2.2: Dependency auto-detection

**Next Priorities:**
- Semantic versioning for production use
- Improve test coverage to 70%+
- Address validation warnings

## Why This Matters

Traditional package managers (npm, pip, cargo) were designed when humans wrote all code. In the AI era, we need package managers that AI can use autonomously.

**Traditional Flow:**
```
AI → Writes everything from scratch → Duplicate implementations → Technical debt
```

**Cartographer Flow:**
```
AI → Searches library → Finds widget → Installs → Integrates → Rates
                ↓
         Gardener extracts patterns
                ↓
         Library grows autonomously
```

**Result:** A self-improving development ecosystem where every project makes the next one easier.

## The Elegant Insight

The elegance of Cartographer is that it inverts the traditional relationship between code and tooling:

**Traditional:** Tools serve human developers who write and manage code

**Cartographer:** Tools serve AI agents who assemble, evaluate, and evolve a shared codebase

By treating AI as the primary user, Cartographer creates a feedback loop where:
1. Builders assemble features from widgets
2. Gardeners extract patterns back to the library
3. Explorers have more options for future features
4. The library quality improves through ratings and use

This transforms AI coding from "regenerate everything" to "curate and compose" - which is fundamentally more scalable and maintainable.

---

**Architecture Files:**
- `/home/Vinscen/Cartographer/cartographer.py` - Main CLI engine (2013 lines)
- `/home/Vinscen/Cartographer/widget_factory.py` - Autonomous widget generator
- `/home/Vinscen/Cartographer/Widget_Library/` - 46 widgets
- `/home/Vinscen/Cartographer/Blueprints/` - 11 blueprints
- `/home/Vinscen/Cartographer/.agent/` - Agent protocols
