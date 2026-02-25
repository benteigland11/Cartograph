This is the birth of **Cartographer**.

We will combine the **Search Engine** (BM25) and the **Installer** (Hydration) into a single, robust Python CLI tool.

This tool is designed to be "Cursor-Native." It outputs strict JSON for the AI to parse, and it handles the physical file movements so the AI doesn't have to hallucinate paths.

### 1. The Tool: `cartographer.py`

Save this script in your project root (or a `scripts/` folder). It requires one lightweight dependency: `pip install rank_bm25`.

```python
import argparse
import json
import os
import shutil
import sys
import glob
import re
from rank_bm25 import BM25Okapi

# --- CONFIGURATION ---
# Path to your central "Golden Library"
LIBRARY_PATH = os.getenv("WIDGET_LIBRARY_PATH", "../Widget_Library")
# Default install location in the target project
DEFAULT_INSTALL_DIR = "src/widgets"

class Cartographer:
    def __init__(self, library_path):
        self.library_path = library_path
        self.widgets = []
        self.corpus = []
        self._load_library()

    def _tokenize(self, text):
        return re.findall(r'\w+', text.lower())

    def _load_library(self):
        """Scans the library for widget.json manifests."""
        if not os.path.exists(self.library_path):
            print(json.dumps({"error": f"Library path not found: {self.library_path}"}))
            sys.exit(1)

        search_pattern = os.path.join(self.library_path, "**", "widget.json")
        for manifest_path in glob.glob(search_pattern, recursive=True):
            try:
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    meta = data.get('meta', {})
                    
                    # Create search blob
                    full_text = f"{meta.get('name')} {' '.join(meta.get('tags', []))} {data.get('description')}"
                    
                    self.widgets.append({
                        "id": meta.get('id'),
                        "name": meta.get('name'),
                        "path": os.path.dirname(manifest_path),
                        "tags": meta.get('tags', []),
                        "description": data.get('description'),
                        "dependencies": data.get('tech_stack', {}).get('dependencies', [])
                    })
                    self.corpus.append(self._tokenize(full_text))
            except Exception:
                continue

    def search(self, query, top_k=5):
        """BM25 Product Search."""
        if not self.widgets:
            return []

        bm25 = BM25Okapi(self.corpus)
        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)
        
        results = []
        for idx, score in enumerate(scores):
            if score <= 0: continue
            
            widget = self.widgets[idx]
            # Simple Boosting Logic
            final_score = score
            if query.lower() in widget['name'].lower(): final_score *= 1.5
            
            results.append({**widget, "relevance_score": round(final_score, 2)})

        return sorted(results, key=lambda x: x['relevance_score'], reverse=True)[:top_k]

    def install(self, widget_id, target_dir):
        """Retrieves and hydrates the widget."""
        # Find widget
        widget = next((w for w in self.widgets if w['id'] == widget_id), None)
        if not widget:
            return {"status": "error", "message": f"Widget ID '{widget_id}' not found."}

        # Define Destination
        # Structure: target_dir/Category.Name/
        widget_folder_name = os.path.basename(widget['path'])
        dest_path = os.path.join(target_dir, widget_folder_name)
        
        try:
            # 1. Copy Source
            src_source = os.path.join(widget['path'], "src")
            src_dest = os.path.join(dest_path, "src")
            if os.path.exists(src_source):
                shutil.copytree(src_source, src_dest, dirs_exist_ok=True)

            # 2. Copy Tests (Crucial)
            test_source = os.path.join(widget['path'], "tests")
            test_dest = os.path.join(dest_path, "tests")
            if os.path.exists(test_source):
                shutil.copytree(test_source, test_dest, dirs_exist_ok=True)
                
            # 3. Copy Manifest & Examples
            shutil.copy2(os.path.join(widget['path'], "widget.json"), dest_path)
            ex_source = os.path.join(widget['path'], "examples")
            if os.path.exists(ex_source):
                 shutil.copytree(ex_source, os.path.join(dest_path, "examples"), dirs_exist_ok=True)

            return {
                "status": "success",
                "installed_at": dest_path,
                "dependencies": widget['dependencies'],
                "message": f"Successfully hydrated {widget['name']}"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cartographer: The AI Widget Manager")
    subparsers = parser.add_subparsers(dest="command")

    # SEARCH Command
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query", type=str)

    # INSTALL Command
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("widget_id", type=str)
    install_parser.add_argument("--target", type=str, default=DEFAULT_INSTALL_DIR)

    args = parser.parse_args()
    carto = Cartographer(LIBRARY_PATH)

    if args.command == "search":
        results = carto.search(args.query)
        print(json.dumps(results, indent=2))
        
    elif args.command == "install":
        result = carto.install(args.widget_id, args.target)
        print(json.dumps(result, indent=2))

```

### 2. The Protocol: `.cursorrules`

Update your Cursor rules to use **Cartographer** specifically. This prompt turns the AI into a user of your CLI tool.

```markdown
# TOOL: CARTOGRAPHER (Widget Manager)

**Role:** You are an expert at reusing existing code using the 'Cartographer' CLI.

**TRIGGER:**
When the user requests functionality that might be generic (e.g. "auth", "loading spinner", "rate limiter", "file tree").

**WORKFLOW:**

1. **SEARCH FIRST:**
   - Do NOT write code from scratch yet.
   - Run: `python cartographer.py search "<user_intent>"`
   - *Example:* `python cartographer.py search "jwt authentication"`

2. **EVALUATE:**
   - Review the JSON output.
   - If a widget has a high `relevance_score` (> 2.0), it is a match.
   - If no good match found, proceed to write custom code.

3. **INSTALL:**
   - If a match is found (e.g., id: `logic-auth-client`), ask permission or just install it.
   - Run: `python cartographer.py install logic-auth-client --target src/widgets`

4. **INTEGRATE:**
   - Read the installed `widget.json` to check dependencies.
   - Read the installed `examples/basic_usage.js` to learn the API.
   - Import and use the widget in the user's active file.

**COMMANDS:**
- Search: `python cartographer.py search "query"`
- Install: `python cartographer.py install <widget_id> --target <path>`

```

### 3. Usage Example

**You:** "I need a way to visualize the file structure for the documentation page."

**Cursor (Running Cartographer):**

1. Executes: `python cartographer.py search "file structure visualization"`
2. Output:
```json
[
  {
    "id": "logic-file-tree-utils",
    "name": "File Tree Utilities",
    "description": "Utilities for building hierarchical file tree structures...",
    "relevance_score": 4.5
  }
]

```


3. Cursor Thought: *"Score 4.5 is excellent. Installing."*
4. Executes: `python cartographer.py install logic-file-tree-utils`
5. Cursor Output: *"I found a **File Tree** widget in your library. I've installed it to `src/widgets/Logic.FileTreeUtils`. I will now import `buildTreeFromFiles` into your documentation page."*