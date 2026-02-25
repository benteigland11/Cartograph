# Widget Quality & Review Workflow

## Overview

Cartographer uses a **two-tier contribution system** to ensure all widgets added to the library meet the "Gold Standard" while enabling AI assistants to work efficiently:

1. **Standardized Import (AI)** - AI prepares, validates, and registers widgets.
2. **Review & Approval (Human)** - Humans review and approve/reject similarity-flagged contributions.

---

## The "Gold Standard" Principle

Unlike the legacy extraction system, we no longer allow "skeleton" widgets in the library. Every widget must be fully functional, documented, and tested *before* registration.

**A Gold Standard widget requires:**
- **Finalized source code** in `src/`.
- **Passing unit tests** in `tests/`.
- **Working usage examples** in `examples/`.
- **Zero [TODO] tags** in the `widget.json` manifest.

---

## AI Contribution Workflow

### 1. Scaffold Workspace
When a project is finished, the AI creates a local workspace to prepare the contribution.
```bash
python cartographer.py scaffold --id logic-data-parser --name "Data Parser"
```

### 2. Populate & Polish
The AI populates the `./contribution` folder:
- Moves stable code to `src/`.
- Writes comprehensive tests to `tests/`.
- Creates a working example in `examples/`.
- Fills out `widget.json` metadata completely.

### 3. Validate
The AI runs the automated gatekeeper. If any validation fails (missing files, leftover `[TODO]` tags, failing tests), the AI must fix them.
```bash
python cartographer.py validate --path ./contribution
```

### 4. Register
Once validated, the AI registers the widget.
```bash
python cartographer.py register --path ./contribution
```

**Outcome:**
- **Unique Widget** → Moved directly to `Widget_Library/` (Searchable immediately).
- **Duplicate Flagged** → Moved to `Pending_Widgets/` (Requires human review).

---

## Human Review Workflow

### 1. Run Review Command
Humans review widgets that were flagged as potentially similar to existing library entries.
```bash
python cartographer.py review
```

### 2. Decision Making
For each pending widget, the reviewer sees:
- The provided **Differentiation** explanation.
- A list of **Similar Widgets** already in the library.
- Option to **Inspect** the full code and manifest.

**Review Actions:**
- **[a]pprove**: Moves the widget to `Widget_Library/` and marks it searchable.
- **[r]eject**: Deletes the contribution permanently.
- **[i]nspect**: Views the manifest and code.
- **[s]kip**: defers the decision until later.

---

## Folder Structure

```
Widget_Library/          ← Approved "Gold Standard" widgets
Pending_Widgets/         ← Flagged contributions awaiting review
.cartographer/
  extraction_log.json    ← Audit trail of all registrations
```

## Summary

| Phase | Responsibility | Tool | Goal |
|-------|----------------|------|------|
| **Preparation** | AI Assistant | `scaffold` | Create structure |
| **Development** | AI Assistant | Manual | Reach Gold Standard |
| **Validation** | AI Assistant | `validate` | Automated quality check |
| **Registration** | AI Assistant | `register` | Duplicate check & Import |
| **Audit** | Human Reviewer | `review` | Final gate for duplicates |

**Key Principle:** *AI builds quality; humans enforce uniqueness.*
