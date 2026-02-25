# Cartographer: The AI-Native Package Manager

**Cartographer** is a CLI tool for discovering, installing, and managing "verified assets" (code widgets and architectural blueprints) for your codebase.

**Core Philosophy**: Reuse battle-tested code first; write custom code second.

## 0. Setup & Execution

The tool is globally installed. You can run it from any directory using the `cartographer` command.

```bash
cartographer <command> [args]
```

---

## 1. Asset Discovery & Acquisition

### Unified Search
Find assets in both your local installation and the remote library with a single command.
```bash
cartographer search "<query>" [--domain <frontend|backend|all>] [--language <python|javascript|...>]
```
**Output Features**:
*   **Relevance Score**: How well it matches your query.
*   **Lines of Code (LoC)**: A dynamically calculated proxy for complexity (Script vs. Framework).
*   **Installed Matches**: Items you already have.
*   **Library Discovery**: New items available for download.

### Inspection
Evaluate an asset's quality, documentation, and dependencies before installing.
```bash
cartographer inspect <id> [--examples|--source|--tests|--all]
```
*   Use `--examples` to see how it is used.
*   Use `--source` to audit the code quality.

### Installation
Download an asset into your project's `cartographer/` directory.
```bash
cartographer install <id> [--target cartographer]
```
*   **Result**: Assets are placed in `cartographer/widgets/<Category>.<Name>`.
*   **Note**: This is a non-destructive download. It does not overwrite your project source code.

---

## 2. Integration Patterns (Flexible Usage)

Cartographer delivers assets to `cartographer/`, but **you determine how to consume them** based on your project's needs.

### Common Patterns
While there are no strict rules, these are the typical usage patterns:

*   **Reference Strategy (Importing)**
    *   *Action*: Import or reference directly from `cartographer/widgets/...`.
    *   *Benefit*: Easy to update later (just run `install` again).
    *   *Use Case*: Assets used "as-is", such as complex logic, standard utilities, or libraries where you don't need to modify the internal code.

*   **Template Strategy (Copying)**
    *   *Action*: Copy source files from `cartographer/widgets/...` to your own source tree.
    *   *Benefit*: Full ownership to customize code, styling, or configuration.
    *   *Use Case*: Assets used as a "starting point" (like boilerplates), or when technical constraints (like npm bundlers not liking external paths) require the file to be in your source tree.

**The Golden Rule**: If you need to *change* the internal behavior, copy it to your project. If you just need to *use* it, import it. **NEVER manually edit code inside the `cartographer/` directory.**

---

## 3. Maintenance & Feedback

### Drift Detection (Integrity & Updates)
Check if your installed assets are out of sync with the library or have been improperly modified.
```bash
cartographer compare --all
```
**Statuses**:
*   **Clean**: Matches the library exactly.
*   **Modified**: Version matches, but the local code has been edited (Breakage of Golden Rule).
*   **Outdated**: A newer version is available in the library.

### Rating & Feedback
Improve the ecosystem by rating assets **after** you have integrated and tested them.
```bash
cartographer rate ./cartographer/widgets/Logic.RateLimiter --score 5 --comment "Works as advertised"
```
*   **Requirement**: You must provide the path to the *installed* widget (Proof of Use).
*   **Scale**: 1 (Broken) to 5 (Perfect).

---

## 4. Contribution (The Cycle)

Improve the library by fixing bugs, adding new assets, or creating entirely new categories.

### The Checkout/Checkin Loop
1.  **Checkout**: Pull a widget into a sandbox.
    ```bash
    cartographer checkout logic-rate-limiter
    ```
2.  **Refine**: Edit code, add tests, fix bugs in the `./checkouts/` folder.
3.  **Validate**: Ensure it meets the Gold Standard.
    ```bash
    cartographer validate --path ./checkouts/logic-rate-limiter
    ```
    **Supported Languages & Test Runners**:
    Cartographer uses a **Project-First** validation strategy. It automatically detects and runs tests for:
    *   **Python**: `pytest` or `python`
    *   **JavaScript/TypeScript**: `vitest`
    *   **Go**: `go test`
    *   **Rust**: `cargo test`
    *   **C/C++**: `CMake` or `Makefile`
    *   **Java**: `Maven` or `Gradle`
    *   **C#**: `dotnet test`
    
    *Note: The presence of a project file (e.g., `Cargo.toml`, `*.csproj`) satisfies the test requirement.*

4.  **Checkin**: Submit back to the library.
    ```bash
    cartographer checkin ./checkouts/logic-rate-limiter --reason "Fixed race condition"
    ```

### Creating New Widgets & Categories
The library is **category-agnostic**. You can create any category you need (e.g., `Infra`, `Audio`, `Data`, `Game`).

```bash
# Creates 'Audio.Transcriber'
cartographer checkout --new --name "Whisper Transcriber" --type widget
# (When prompted for ID, use 'audio-transcriber')
```

**Naming Convention**: The folder structure is derived from the ID (`category-name`).
*   ID `infra-aws-bucket` → Folder `Infra.AwsBucket`
*   ID `data-csv-parser` → Folder `Data.CsvParser`

Choose descriptive IDs to keep the library organized.

---

## Command Summary

| Command | Purpose |
| :--- | :--- |
| `search` | Find assets (local & remote). |
| `inspect` | View metadata, code, and examples. |
| `install` | Download asset & its dependencies to `cartographer/`. |
| `uninstall` | Remove an asset folder from the local project. |
| `compare` | Check integrity and version status. |
| `popular` | List the most used widgets. |
| `rate` | Provide quality feedback. |
| `checkout` | Start editing/creating an asset. |
| `validate` | Run quality checks (tests/docs). |
| `checkin` | Save changes to the library. |
