import sys
import subprocess
import importlib.util

# --- SELF-HEAL: Install dependencies if missing ---
if importlib.util.find_spec("rank_bm25") is None:
    print("Installing required dependency: rank_bm25...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rank_bm25"])
# --------------------------------------------------

import argparse
import json
import os
import shutil
import glob
import re
import hashlib
import datetime
import difflib
from rank_bm25 import BM25Okapi

# --- OPTIONAL: Meilisearch backend ---
try:
    import meilisearch
    MEILISEARCH_AVAILABLE = True
except ImportError:
    MEILISEARCH_AVAILABLE = False

# --- CONFIGURATION ---
# Determine where this script is located on disk
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Look for "Widget_Library" and "Blueprints" either in the same folder or one level up
LOCAL_LIB = os.path.join(SCRIPT_DIR, "Widget_Library")
PARENT_LIB = os.path.join(SCRIPT_DIR, "../Widget_Library")
LOCAL_BLUEPRINTS = os.path.join(SCRIPT_DIR, "Blueprints")
PARENT_BLUEPRINTS = os.path.join(SCRIPT_DIR, "../Blueprints")

DEFAULT_LIB_PATH = LOCAL_LIB if os.path.exists(LOCAL_LIB) else PARENT_LIB
LIBRARY_PATH = os.getenv("WIDGET_LIBRARY_PATH", DEFAULT_LIB_PATH)

DEFAULT_BLUEPRINT_PATH = LOCAL_BLUEPRINTS if os.path.exists(LOCAL_BLUEPRINTS) else PARENT_BLUEPRINTS
BLUEPRINT_PATH = os.getenv("BLUEPRINT_PATH", DEFAULT_BLUEPRINT_PATH)

# Pending widgets (needs review)
LOCAL_PENDING = os.path.join(SCRIPT_DIR, "Pending_Widgets")
PARENT_PENDING = os.path.join(SCRIPT_DIR, "../Pending_Widgets")
DEFAULT_PENDING_PATH = LOCAL_PENDING if os.path.exists(LOCAL_PENDING) else PARENT_PENDING
PENDING_WIDGETS_PATH = os.getenv("PENDING_WIDGETS_PATH", DEFAULT_PENDING_PATH)

# Extraction audit log
CARTOGRAPHER_DIR = os.path.join(SCRIPT_DIR, ".cartographer")
EXTRACTION_LOG_PATH = os.path.join(CARTOGRAPHER_DIR, "extraction_log.json")
INSTALL_STATS_PATH = os.path.join(CARTOGRAPHER_DIR, "stats.json")

DEFAULT_INSTALL_DIR = "cartographer"

class Cartographer:
    def __init__(self, library_path, blueprint_path=None, search_backend='bm25'):
        self.library_path = library_path
        self.blueprint_path = blueprint_path
        self.widgets = []
        self.corpus = []
        self.search_backend = search_backend
        self.install_stats = self._load_install_stats()
        self.installed_index = self._load_installed_index()
        self._load_library()
        if self.blueprint_path:
            self._load_blueprints()

        # Initialize Meilisearch if requested
        self._meili_client = None
        self._meili_index = None
        if search_backend == 'meilisearch':
            self._init_meilisearch()

    def _tokenize(self, text):
        tokens = re.findall(r'\w+', text.lower())
        synonym_map = {
            "ai": ["llm", "model"],
            "llm": ["ai", "model"],
            "codefile": ["code", "file", "codefiles"],
            "codefiles": ["code", "files", "codefile"],
            "codefileservice": ["code", "file", "service"],
            "creating": ["create", "creation"],
            "creation": ["create", "creating"],
            "workflow": ["blueprint"],
            "blueprint": ["workflow"]
        }
        expanded = []
        for token in tokens:
            expanded.append(token)
            expanded.extend(synonym_map.get(token, []))
        return expanded

    def _init_meilisearch(self):
        """Initialize Meilisearch connection and sync widgets."""
        if not MEILISEARCH_AVAILABLE:
            print("Warning: Meilisearch not installed. Falling back to BM25.")
            self.search_backend = 'bm25'
            return

        try:
            self._meili_client = meilisearch.Client("http://localhost:7700")
            self._meili_client.health()  # Check connection
            self._meili_index = self._meili_client.index("cartographer_widgets")

            # Sync widgets to Meilisearch
            self._sync_to_meilisearch()
        except Exception as e:
            print(f"Warning: Meilisearch unavailable ({e}). Falling back to BM25.")
            self.search_backend = 'bm25'

    def _sync_to_meilisearch(self):
        """Sync all widgets to Meilisearch index."""
        if not self._meili_index or not self.widgets:
            return

        # Prepare documents for Meilisearch
        docs = []
        for i, widget in enumerate(self.widgets):
            doc = {
                "id": widget["id"],
                "idx": i,  # Original index for result lookup
                "name": widget.get("name", ""),
                "description": widget.get("description", ""),
                "tags": " ".join(widget.get("tags", [])),
                "domain": widget.get("domain", ""),
                "language": widget.get("language", "") if isinstance(widget.get("language"), str) else " ".join(widget.get("language", [])),
                "type": widget.get("type", "widget"),
            }
            docs.append(doc)

        # Index documents
        task = self._meili_index.add_documents(docs)
        self._wait_for_task(task.task_uid)

        # Configure searchable fields
        self._meili_index.update_searchable_attributes([
            "name", "description", "tags", "id"
        ])
        self._meili_index.update_filterable_attributes([
            "domain", "language", "type"
        ])

    def _wait_for_task(self, task_uid, timeout=30):
        """Wait for Meilisearch task to complete."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            task = self._meili_client.get_task(task_uid)
            if task.status in ('succeeded', 'failed'):
                return
            time.sleep(0.1)

    def _normalize_code(self, code):
        """Strip comments and empty lines to focus on logic."""
        # Strip python/coffee/shell comments
        code = re.sub(r'#.*', '', code)
        # Strip JS/TS/Java comments
        code = re.sub(r'//.*', '', code)
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        # Strip extra whitespace and empty lines
        lines = [l.strip() for l in code.splitlines() if l.strip()]
        return " ".join(lines)

    def _calculate_implementation_hash(self, path):
        """Calculate a stable hash of the entire src/ folder."""
        src_path = os.path.join(path, "src")
        if not os.path.exists(src_path):
            return None
        
        hasher = hashlib.md5()
        # Sort files to ensure stable hash
        for root, dirs, files in os.walk(src_path):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for names in sorted(files):
                if names.endswith('.pyc'):
                    continue
                filepath = os.path.join(root, names)
                with open(filepath, 'rb') as f:
                    # Hash normalized content to be whitespace-insensitive if possible, 
                    # but for hard-block we'll do raw content to be safe.
                    hasher.update(f.read())
        return hasher.hexdigest()

    def _diff_against_library(self, path, item_id):
        """Generate a unified diff of src/ files between a local widget and its library version."""
        existing = next((w for w in self.widgets if w['id'] == item_id), None)
        if not existing:
            return None

        lib_src = os.path.join(existing['path'], "src")
        local_src = os.path.join(path, "src")

        if not os.path.exists(lib_src) or not os.path.exists(local_src):
            return None

        # Collect relative file paths from both sides
        def collect_files(base):
            result = {}
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for fname in files:
                    if fname.endswith('.pyc'):
                        continue
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, base)
                    result[rel] = full
            return result

        lib_files = collect_files(lib_src)
        local_files = collect_files(local_src)
        all_keys = sorted(set(lib_files) | set(local_files))

        files_changed = []
        files_added = []
        files_removed = []
        diff_parts = []

        for rel in all_keys:
            in_lib = rel in lib_files
            in_local = rel in local_files

            if in_lib and not in_local:
                files_removed.append(rel)
                lib_lines = open(lib_files[rel]).readlines()
                diff_parts.extend(difflib.unified_diff(lib_lines, [], fromfile=f"a/src/{rel}", tofile=f"b/src/{rel}"))
            elif in_local and not in_lib:
                files_added.append(rel)
                local_lines = open(local_files[rel]).readlines()
                diff_parts.extend(difflib.unified_diff([], local_lines, fromfile=f"a/src/{rel}", tofile=f"b/src/{rel}"))
            else:
                lib_lines = open(lib_files[rel]).readlines()
                local_lines = open(local_files[rel]).readlines()
                file_diff = list(difflib.unified_diff(lib_lines, local_lines, fromfile=f"a/src/{rel}", tofile=f"b/src/{rel}"))
                if file_diff:
                    files_changed.append(rel)
                    diff_parts.extend(file_diff)

        if not files_changed and not files_added and not files_removed:
            return None

        return {
            "files_changed": files_changed,
            "files_added": files_added,
            "files_removed": files_removed,
            "diff": "".join(diff_parts)
        }

    def _count_tests(self, widget_path):
        """Count test files in the widget's tests directory."""
        tests_dir = os.path.join(widget_path, "tests")
        if not os.path.exists(tests_dir):
            return 0
        # Count all test patterns: test_*.*, *_test.go, *.rs
        test_files = glob.glob(os.path.join(tests_dir, "test_*.*"))
        test_files += glob.glob(os.path.join(tests_dir, "*_test.go"))
        test_files += glob.glob(os.path.join(tests_dir, "*.rs"))
        return len(set(test_files))  # Remove duplicates

    def _load_reviews(self, item_path):
        """Load reviews from reviews.json and calculate average rating."""
        review_path = os.path.join(item_path, "reviews.json")
        if not os.path.exists(review_path):
            return {"rating": 0, "count": 0, "reviews": [], "version_averages": {}}
        
        try:
            with open(review_path, 'r') as f:
                data = json.load(f)
                reviews = data.get("reviews", [])
                if not reviews:
                    return {"rating": 0, "count": 0, "reviews": [], "version_averages": {}}
                
                total_score = sum(r.get("rating", 0) for r in reviews)
                avg_rating = round(total_score / len(reviews), 1)
                
                # Group by version to find regressions
                version_ratings = {}
                for r in reviews:
                    v = r.get("version", "unknown")
                    if v not in version_ratings: version_ratings[v] = []
                    version_ratings[v].append(r.get("rating", 0))
                
                v_averages = {v: sum(rs)/len(rs) for v, rs in version_ratings.items()}
                
                return {
                    "rating": avg_rating,
                    "count": len(reviews),
                    "reviews": reviews,
                    "version_averages": v_averages
                }
        except:
            return {"rating": 0, "count": 0, "reviews": [], "version_averages": {}}

    def _load_install_stats(self):
        """Load install counts from stats.json."""
        if not os.path.exists(INSTALL_STATS_PATH):
            return {}
        try:
            with open(INSTALL_STATS_PATH, 'r') as f:
                data = json.load(f)
                return data.get("installs", {})
        except Exception:
            return {}

    def _save_install_stats(self):
        os.makedirs(CARTOGRAPHER_DIR, exist_ok=True)
        temp_path = INSTALL_STATS_PATH + ".tmp"
        try:
            with open(temp_path, 'w') as f:
                json.dump({"installs": self.install_stats}, f, indent=2)
            os.replace(temp_path, INSTALL_STATS_PATH)
        except Exception as e:
            print(f"⚠️ Failed to save stats: {e}", file=sys.stderr)

    def _load_installed_index(self):
        """Index locally installed widgets/blueprints in ./cartographer for quick lookup."""
        installed = {}
        base_dir = os.path.join(os.getcwd(), DEFAULT_INSTALL_DIR)
        widget_root = os.path.join(base_dir, "widgets")
        blueprint_root = os.path.join(base_dir, "blueprints")

        def scan(root, manifest_name, item_type):
            if not os.path.exists(root):
                return
            for manifest_path in glob.glob(os.path.join(root, "**", manifest_name), recursive=True):
                try:
                    with open(manifest_path, 'r') as f:
                        data = json.load(f)
                        meta = data.get("meta", {})
                        item_id = meta.get("id")
                        if not item_id:
                            continue
                        installed.setdefault(item_id, []).append({
                            "path": os.path.dirname(manifest_path),
                            "type": item_type
                        })
                except Exception:
                    continue

        scan(widget_root, "widget.json", "widget")
        scan(blueprint_root, "blueprint.json", "blueprint")
        # Also scan widgets installed inside blueprints (self-contained blueprints)
        if os.path.exists(blueprint_root):
            for bp_dir in os.listdir(blueprint_root):
                bp_widgets = os.path.join(blueprint_root, bp_dir, "widgets")
                if os.path.isdir(bp_widgets):
                    scan(bp_widgets, "widget.json", "widget")
        return installed

    def _get_installed_info(self, item_id):
        return self.installed_index.get(item_id, [])

    def _increment_install_count(self, item_id):
        """Increments install count and persists to disk. Reloads first to prevent race conditions."""
        self.install_stats = self._load_install_stats()
        self.install_stats[item_id] = self.install_stats.get(item_id, 0) + 1
        self._save_install_stats()
        
        # Update in-memory cache if widget exists so subsequent search/inspect in same process see it
        for w in self.widgets:
            if w['id'] == item_id:
                w['install_count'] = self.install_stats[item_id]
                break

    def _get_install_count(self, item_id):
        return self.install_stats.get(item_id, 0)

    def _normalize_composed_of(self, composed_of):
        """Normalize composed_of to list of {id, version} dicts.

        Handles both old format (flat list of strings) and new format (list of dicts).
        """
        result = []
        for item in composed_of:
            if isinstance(item, str):
                result.append({"id": item, "version": None})
            elif isinstance(item, dict):
                result.append({"id": item["id"], "version": item.get("version")})
        return result

    def _extract_composed_ids(self, composed_of):
        """Extract just the IDs from a composed_of list (handles both formats)."""
        return [entry["id"] for entry in self._normalize_composed_of(composed_of)]

    def _normalize_language(self, lang):
        """Normalize language name for use in IDs (lowercase)."""
        if not lang:
            return "unknown"

        # Handle common language names
        lang_lower = lang.lower()

        # Normalize common variants
        if lang_lower in ["javascript", "js", "ecmascript"]:
            return "javascript"
        elif lang_lower in ["typescript", "ts"]:
            return "typescript"
        elif lang_lower in ["python", "py"]:
            return "python"
        elif lang_lower in ["rust", "rs"]:
            return "rust"
        elif lang_lower in ["go", "golang"]:
            return "go"
        elif lang_lower in ["java"]:
            return "java"
        elif lang_lower in ["c++", "cpp", "cxx"]:
            return "cpp"
        elif lang_lower in ["c"]:
            return "c"
        elif lang_lower in ["c#", "csharp"]:
            return "csharp"
        elif lang_lower in ["hip", "hip c++", "hipc++"]:
            return "hip"
        else:
            return lang_lower.replace(" ", "").replace("-", "")

    def _load_library(self):
        """Scans the library, handles legacy schemas, and infers domains."""
        if not os.path.exists(self.library_path):
            print(json.dumps({"error": f"Library path not found: {self.library_path}"}))
            sys.exit(1)

        search_pattern = os.path.join(self.library_path, "**", "widget.json")
        found = [p for p in glob.glob(search_pattern, recursive=True) if "history" not in p]
        for manifest_path in found:
            try:
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    # Support both root-level props (legacy) and nested 'meta' (standard)
                    meta = data.get('meta', data)
                    
                    name = meta.get('name', 'Unknown Widget')
                    tags = meta.get('tags', [])
                    desc = data.get('description', '')
                    
                    # --- SMART DOMAIN INFERENCE ---
                    domain = meta.get('domain', 'universal').lower()
                    if domain == 'universal':
                        tags_str = " ".join(tags).lower()
                        if any(x in tags_str for x in ['react', 'ui', 'css', 'jsx', 'frontend']):
                            domain = 'frontend'
                        elif any(x in tags_str for x in ['python', 'api', 'sql', 'fastapi', 'backend']):
                            domain = 'backend'
                    # ------------------------------

                    widget_path = os.path.dirname(manifest_path)
                    test_count = self._count_tests(widget_path)
                    review_data = self._load_reviews(widget_path)
                    
                    # --- IMPLEMENTATION AWARE SEARCH ---
                    # Index source code tokens to catch logic similarity
                    code_tokens = ""
                    total_lines = 0
                    src_dir = os.path.join(widget_path, "src")
                    if os.path.exists(src_dir):
                        for src_file in glob.glob(os.path.join(src_dir, "*.*")):
                            try:
                                with open(src_file, 'r') as f:
                                    content = f.read()
                                    code_tokens += " " + self._normalize_code(content)
                                    total_lines += len(content.splitlines())
                            except: pass
                    
                    # Also index reviews for better search discovery
                    review_tokens = " ".join(r.get("comment", "") for r in review_data["reviews"])

                    # Index gpu_targets for search (e.g. "gfx1100" queries)
                    gpu_targets = data.get('tech_stack', {}).get('gpu_targets', [])
                    gpu_tokens = " ".join(gpu_targets)

                    full_text = f"{name} {' '.join(tags)} {desc} {code_tokens} {review_tokens} {gpu_tokens}"
                    implementation_hash = self._calculate_implementation_hash(widget_path)
                    version = meta.get('version', '1.0.0')

                    # Check for regression (current version vs lifetime)
                    regression = False
                    if version in review_data["version_averages"]:
                        current_v_avg = review_data["version_averages"][version]
                        if review_data["rating"] - current_v_avg > 1.0:
                            regression = True

                    self.widgets.append({
                        "id": meta.get('id', os.path.basename(os.path.dirname(manifest_path))),
                        "name": name,
                        "version": version,
                        "type": "widget",
                        "widget_type": meta.get('widget_type', 'library'),
                        "path": widget_path,
                        "tags": tags,
                        "domain": domain,
                        "description": desc,
                        "language": data.get('tech_stack', {}).get('language', 'unknown'),
                        "dependencies": data.get('tech_stack', {}).get('dependencies', []),
                        "gpu_targets": gpu_targets,
                        "depends_on": data.get('depends_on', []),
                        "integration": data.get('integration_guide', {}),
                        "test_count": test_count,
                        "maturity": meta.get('maturity', 'unknown'),
                        "implementation_hash": implementation_hash,
                        "installed_at": self._get_installed_info(meta.get('id', os.path.basename(os.path.dirname(manifest_path)))),
                        "is_installed": bool(self._get_installed_info(meta.get('id', os.path.basename(os.path.dirname(manifest_path))))),
                        "install_count": self._get_install_count(meta.get('id', os.path.basename(os.path.dirname(manifest_path)))),
                        "rating": review_data["rating"],
                        "review_count": review_data["count"],
                        "reviews": review_data["reviews"],
                        "regression": regression,
                        "lines_of_code": total_lines
                    })
                    self.corpus.append(self._tokenize(full_text))
            except Exception:
                continue

    def _load_blueprints(self):
        """Scans the blueprint directory."""
        if not self.blueprint_path or not os.path.exists(self.blueprint_path):
            return

        search_pattern = os.path.join(self.blueprint_path, "**", "blueprint.json")
        found = [p for p in glob.glob(search_pattern, recursive=True) if "history" not in p]
        for manifest_path in found:
            try:
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    meta = data.get('meta', {})
                    name = meta.get('name', 'Unknown Blueprint')
                    tags = meta.get('tags', [])
                    desc = data.get('description', '')
                    
                    blueprint_path = os.path.dirname(manifest_path)
                    test_count = self._count_tests(blueprint_path)
                    review_data = self._load_reviews(blueprint_path)
                    composed_of_raw = data.get('composed_of', [])
                    composed_of_normalized = self._normalize_composed_of(composed_of_raw)
                    composed_ids = [entry["id"] for entry in composed_of_normalized]
                    version = meta.get('version', '1.0.0')

                    # Index component IDs - if the list is identical, it's a duplicate
                    component_tokens = " ".join(composed_ids)
                    # Also index reviews
                    review_tokens = " ".join(r.get("comment", "") for r in review_data["reviews"])

                    # --- IMPLEMENTATION AWARE SEARCH (Blueprints) ---
                    total_lines = 0
                    src_dir = os.path.join(blueprint_path, "src")
                    if os.path.exists(src_dir):
                        for src_file in glob.glob(os.path.join(src_dir, "*.*")):
                            try:
                                with open(src_file, 'r') as f:
                                    total_lines += len(f.readlines())
                            except: pass
                    # ------------------------------------------------

                    id_token = meta.get('id', os.path.basename(os.path.dirname(manifest_path)))
                    id_readable = id_token.replace('-', ' ')
                    widget_lookup = {w["id"]: w for w in self.widgets}
                    component_names = [
                        widget_lookup[cid]["name"]
                        for cid in composed_ids
                        if cid in widget_lookup
                    ]
                    component_tags = []
                    for cid in composed_ids:
                        if cid in widget_lookup:
                            component_tags.extend(widget_lookup[cid].get("tags", []))
                    blueprint_tags = list(dict.fromkeys(tags + component_tags))
                    full_text = (
                        f"{id_token} {id_readable} {name} {' '.join(blueprint_tags)} {desc} "
                        f"{component_tokens} {' '.join(component_names)} {review_tokens}"
                    )

                    # Regression check
                    regression = False
                    if version in review_data["version_averages"]:
                        current_v_avg = review_data["version_averages"][version]
                        if review_data["rating"] - current_v_avg > 1.0:
                            regression = True

                    self.widgets.append({
                        "id": meta.get('id', os.path.basename(os.path.dirname(manifest_path))),
                        "name": name,
                        "version": version,
                        "type": "blueprint",
                        "path": blueprint_path,
                        "tags": blueprint_tags,
                        "domain": meta.get('domain', 'universal'),
                        "description": desc,
                        "composed_of": composed_of_normalized,
                        "configuration": data.get('configuration', {}),
                        "test_count": test_count,
                        "maturity": meta.get('maturity', 'unknown'),
                        "installed_at": self._get_installed_info(meta.get('id', os.path.basename(os.path.dirname(manifest_path)))),
                        "is_installed": bool(self._get_installed_info(meta.get('id', os.path.basename(os.path.dirname(manifest_path))))),
                        "install_count": self._get_install_count(meta.get('id', os.path.basename(os.path.dirname(manifest_path)))),
                        "rating": review_data["rating"],
                        "review_count": review_data["count"],
                        "reviews": review_data["reviews"],
                        "regression": regression,
                        "lines_of_code": total_lines
                    })
                    self.corpus.append(self._tokenize(full_text))
            except Exception:
                continue

    def search(self, query, domain_filter=None, language_filter=None, type_filter=None, top_k=15):
        if not self.widgets:
            return {"installed": [], "library": []}

        # Use Meilisearch if available and configured
        if self.search_backend == 'meilisearch' and self._meili_index:
            return self._search_meilisearch(query, domain_filter, language_filter, type_filter, top_k)

        bm25 = BM25Okapi(self.corpus)
        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        results = []
        for idx, score in enumerate(scores):
            widget = self.widgets[idx]

            # --- METADATA GATE ---
            # Require query to match widget metadata (name/tags/description/id).
            meta_text = f"{widget.get('id','')} {widget.get('name','')} {' '.join(widget.get('tags', []))} {widget.get('description','')}"
            meta_tokens = self._tokenize(meta_text)
            meta_match_tokens = set(tokenized_query) & set(meta_tokens)
            meta_score = float(len(meta_match_tokens))
            if query.lower() in widget.get('name', '').lower() or query.lower() in widget.get('id', '').lower():
                meta_score += 2.0
            if meta_score <= 0:
                continue

            # --- DOMAIN FILTER ---
            if domain_filter and domain_filter != 'all':
                # 'universal' widgets appear in both searches
                if widget['domain'] != domain_filter and widget['domain'] != 'universal':
                    continue

            # --- LANGUAGE FILTER ---
            if language_filter:
                w_lang = widget.get('language', '')
                filter_val = language_filter.lower()

                # Normalize widget language to a set of strings
                if isinstance(w_lang, list):
                    w_langs = set(l.lower() for l in w_lang)
                else:
                    # Handle "Python" or "Python, Rust" or "Python/Rust"
                    w_langs = set(l.strip().lower() for l in str(w_lang).replace(',', ' ').replace('/', ' ').split())

                if filter_val not in w_langs:
                    continue

            # --- TYPE FILTER (widget vs blueprint) ---
            if type_filter and type_filter != 'all':
                if widget.get('type', 'widget') != type_filter:
                    continue

            final_score = score
            
            # --- HOTFIX: BOOST BEFORE DISCARDING ---
            # Even if BM25 score is 0, if the query is a substring of the name, we want it!
            if query.lower() in widget['name'].lower():
                final_score += 2.0  # <--- This saves "Auth" matching "Authenticated"
            
            # Fallback for short queries/documents where BM25 might return 0
            matching_tokens = set(tokenized_query) & set(self.corpus[idx])
            if final_score <= 0 and matching_tokens:
                final_score = float(len(matching_tokens))
            
            if final_score <= 0: continue
            
            # Tag matches
            tag_matches = set(tokenized_query) & set(w.lower() for w in widget['tags'])
            if tag_matches:
                final_score += 1.5 * len(tag_matches)
            
            # Store raw widget + score for sorting
            results.append({**widget, "relevance_score": round(final_score, 2)})

        # Sort all results by relevance
        sorted_results = sorted(results, key=lambda x: x['relevance_score'], reverse=True)[:top_k]

        # Split into Context-Aware buckets
        installed_matches = []
        library_matches = []

        for res in sorted_results:
            if res.get('is_installed'):
                # concise summary for installed
                installed_info = res.get('installed_at', [])
                # Handle list vs dict format for installed_info
                if isinstance(installed_info, list) and installed_info:
                    inst_path = installed_info[0].get('path') if isinstance(installed_info[0], dict) else installed_info[0]
                else:
                    inst_path = str(installed_info)

                installed_matches.append({
                    "id": res['id'],
                    "name": res['name'],
                    "version": res['version'],
                    "path": inst_path,
                    "relevance_score": res['relevance_score']
                })
            else:
                # Lean detail for library discovery
                # Exclude heavy fields: reviews, integration, path, implementation_hash, installed_at, is_installed, install_count
                
                # Check for regression to format name
                display_name = res['name']
                if res.get('regression'):
                     display_name = f"⚠️ {res['name']} (REGRESSION IN {res['version']})"

                library_matches.append({
                    "id": res['id'],
                    "name": display_name,
                    "version": res['version'],
                    "description": res['description'],
                    "language": res.get('language', 'unknown'),
                    "dependencies": res.get('dependencies', []),
                    "domain": res['domain'],
                    "maturity": res.get('maturity', 'unknown'),
                    "rating": res.get('rating', 0),
                    "install_count": res.get('install_count', 0),
                    "tags": res.get('tags', []),
                    "relevance_score": res['relevance_score'],
                    "test_count": res.get('test_count', 0),
                    "lines_of_code": res.get('lines_of_code', 0),
                    "widget_type": res.get('widget_type', 'library'),
                    "gpu_targets": res.get('gpu_targets', [])
                })

        return {
            "installed": installed_matches,
            "library": library_matches
        }

    def _search_meilisearch(self, query, domain_filter=None, language_filter=None, type_filter=None, top_k=15):
        """Search using Meilisearch backend."""
        # Build filter string
        filters = []
        if domain_filter and domain_filter != 'all':
            filters.append(f'(domain = "{domain_filter}" OR domain = "universal")')
        if language_filter:
            filters.append(f'language = "{language_filter.lower()}"')
        if type_filter and type_filter != 'all':
            filters.append(f'type = "{type_filter}"')

        search_params = {
            'limit': top_k * 2,  # Get extra to account for post-filtering
            'showRankingScore': True,
        }
        if filters:
            search_params['filter'] = ' AND '.join(filters)

        try:
            results = self._meili_index.search(query, search_params)
        except Exception:
            # Filter might fail if attributes not indexed yet, try without
            results = self._meili_index.search(query, {'limit': top_k * 2, 'showRankingScore': True})

        # Convert hits to widget results
        widget_results = []
        for hit in results.get('hits', []):
            idx = hit.get('idx')
            if idx is None or idx >= len(self.widgets):
                continue
            widget = self.widgets[idx]
            score = hit.get('_rankingScore', 0.5) * 10  # Scale to match BM25 range
            widget_results.append({**widget, "relevance_score": round(score, 2)})

        # Sort and limit
        sorted_results = sorted(widget_results, key=lambda x: x['relevance_score'], reverse=True)[:top_k]

        # Split into installed vs library (same logic as BM25 path)
        installed_matches = []
        library_matches = []

        for res in sorted_results:
            if res.get('is_installed'):
                installed_info = res.get('installed_at', [])
                if isinstance(installed_info, list) and installed_info:
                    inst_path = installed_info[0].get('path') if isinstance(installed_info[0], dict) else installed_info[0]
                else:
                    inst_path = str(installed_info)

                installed_matches.append({
                    "id": res['id'],
                    "name": res['name'],
                    "version": res['version'],
                    "path": inst_path,
                    "relevance_score": res['relevance_score']
                })
            else:
                display_name = res['name']
                if res.get('regression'):
                    display_name = f"⚠️ {res['name']} (REGRESSION IN {res['version']})"

                library_matches.append({
                    "id": res['id'],
                    "name": display_name,
                    "version": res['version'],
                    "description": res['description'],
                    "language": res.get('language', 'unknown'),
                    "dependencies": res.get('dependencies', []),
                    "domain": res['domain'],
                    "maturity": res.get('maturity', 'unknown'),
                    "rating": res.get('rating', 0),
                    "install_count": res.get('install_count', 0),
                    "tags": res.get('tags', []),
                    "relevance_score": res['relevance_score'],
                    "test_count": res.get('test_count', 0),
                    "lines_of_code": res.get('lines_of_code', 0),
                    "widget_type": res.get('widget_type', 'library'),
                    "gpu_targets": res.get('gpu_targets', [])
                })

        return {
            "installed": installed_matches,
            "library": library_matches
        }

    def list_popular(self, limit=10):
        from inspector import list_popular
        return list_popular(self, limit)
    def inspect(self, widget_id, show_examples=False, show_source=False, show_tests=False, version=None):
        from inspector import inspect
        return inspect(self, widget_id, show_examples=show_examples, show_source=show_source,
                       show_tests=show_tests, version=version)
    def _log_registration(self, widget_id, widget_name, similar_widgets, differentiation, needs_review, widget_path):
        from inspector import log_registration
        return log_registration(self, widget_id, widget_name, similar_widgets,
                                differentiation, needs_review, widget_path)
    def review_pending_widgets(self):
        from reviewer import review_pending_widgets
        return review_pending_widgets(self)
    def _approve_widget(self, widget):
        from reviewer import _approve
        return _approve(self, widget)
    def _reject_widget(self, widget):
        from reviewer import _reject
        return _reject(widget)
    def create(self, item_id, language=None, name=None, domain="backend", tags=None,
                target_dir=None, item_type="widget", composed_of=None, gpu_targets=None, widget_type=None):
        from scaffolding import create_widget, create_blueprint
        if item_type == "blueprint":
            return create_blueprint(self, item_id, name=name, domain=domain, tags=tags,
                                    target_dir=target_dir, composed_of=composed_of)
        return create_widget(self, item_id, language=language, name=name, domain=domain,
                             tags=tags, target_dir=target_dir, gpu_targets=gpu_targets,
                             widget_type=widget_type)

    def validate_item(self, path):
        """Perform a 'Gold Standard' check on an item (widget or blueprint) directory."""
        # Track validation checklist
        checklist = []
        errors = []

        def check(description, passed, error_detail=None):
            """Helper to track a validation check."""
            status = "✅" if passed else "❌"
            checklist.append(f"{status} {description}")
            if not passed and error_detail:
                errors.append(error_detail)
            return passed

        # 1. Path exists
        if not check("Path exists", os.path.exists(path), f"Path not found: {path}"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Path not found: {path}"}

        # 2. Manifest file exists
        manifest_path = os.path.join(path, "widget.json")
        item_type = "widget"
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(path, "blueprint.json")
            item_type = "blueprint"

        manifest_exists = os.path.exists(manifest_path)
        if not check(f"{item_type}.json exists", manifest_exists, "Missing widget.json or blueprint.json"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Missing widget.json or blueprint.json"}

        # 3. Valid JSON
        try:
            with open(manifest_path, 'r') as f:
                content = f.read()
            with open(manifest_path, 'r') as f:
                data = json.load(f)
            check(f"{item_type}.json is valid JSON", True)
        except Exception as e:
            check(f"{item_type}.json is valid JSON", False, f"Invalid JSON: {e}")
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Invalid JSON in manifest: {e}"}

        # 4. No [TODO] tags
        todo_count = content.count("[TODO]")
        if not check(f"No [TODO] placeholders in {item_type}.json", todo_count == 0,
                     f"Found {todo_count} [TODO] tag(s) - replace all placeholders"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Placeholders detected! Replace all [TODO] tags in manifest"}

        # 5. Required folders exist and have content
        src_ok = os.path.exists(os.path.join(path, "src")) and os.listdir(os.path.join(path, "src"))
        check("src/ folder exists and has files", src_ok, "src/ folder is missing or empty")

        examples_ok = os.path.exists(os.path.join(path, "examples")) and os.listdir(os.path.join(path, "examples"))
        check("examples/ folder exists and has files", examples_ok, "examples/ folder is missing or empty")

        # Blueprints don't require tests - they're wiring guides, not testable code
        if item_type == "widget":
            # Check for Project-level test indicators
            project_test_indicators = ["Cargo.toml", "CMakeLists.txt", "Makefile", "pom.xml", "build.gradle", "go.mod", "package.json"]
            has_project_file = any(os.path.exists(os.path.join(path, f)) for f in project_test_indicators)
            # Check for C# projects (*.csproj)
            has_csproj = len(glob.glob(os.path.join(path, "*.csproj"))) > 0

            tests_dir_path = os.path.join(path, "tests")
            tests_ok = (os.path.exists(tests_dir_path) and os.listdir(tests_dir_path)) or has_project_file or has_csproj
            check("tests/ folder (or project build file) exists", tests_ok, "tests/ folder is missing/empty and no project build files found")

            if not (src_ok and tests_ok and examples_ok):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "Required structure (src, tests, examples) is incomplete"}
        else:
            # Blueprint: just need src/ and examples/
            check("Blueprints don't require tests/ (they're wiring guides)", True)
            if not (src_ok and examples_ok):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "Required structure (src, examples) is incomplete for blueprint"}

        # ... [Meta fields checks continue] ...


        # 6. Required meta fields
        meta = data.get("meta", {})
        required_meta = ["id", "name", "domain"]
        meta_ok = all(field in meta and meta[field] for field in required_meta)
        missing_fields = [f for f in required_meta if f not in meta or not meta[f]]

        if not check("Required meta fields present (id, name, domain)", meta_ok,
                     f"Missing required field(s): {', '.join(missing_fields)}"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Manifest 'meta.{missing_fields[0]}' is required"}

        # 6b. Canonical schema validation for widgets
        if item_type == "widget":
            # Check meta.type
            has_type = meta.get("type") == "widget"
            check("meta.type = 'widget'", has_type, "meta.type should be 'widget'")
            
            # Check tech_stack structure
            tech_stack = data.get("tech_stack", {})
            has_lang = "language" in tech_stack
            has_lang_ver = "language_version" in tech_stack
            has_deps = "dependencies" in tech_stack
            check("tech_stack.language present", has_lang, "Missing tech_stack.language")
            check("tech_stack.language_version present", has_lang_ver, "Missing tech_stack.language_version")
            check("tech_stack.dependencies present", has_deps, "Missing tech_stack.dependencies")
            
            # Check integration_guide structure
            guide = data.get("integration_guide", {})
            has_usage = "usage" in guide
            has_constraints = "constraints" in guide
            check("integration_guide.usage present", has_usage, "Missing integration_guide.usage (use 'usage' not 'adaptation_notes')")
            check("integration_guide.constraints present", has_constraints, "Missing integration_guide.constraints")
            
            # Check depends_on
            has_depends = "depends_on" in data
            check("depends_on array present", has_depends, "Missing depends_on array")


        # 7. Blueprint-specific validation
        if item_type == "blueprint":
            # 7a. composed_of dependencies exist (handles both old and new format)
            composed_of_raw = data.get("composed_of", [])
            composed_ids = self._extract_composed_ids(composed_of_raw)
            # Check each composed widget exists in library OR in local widgets/ subdirectory
            local_widgets_dir = os.path.join(path, "widgets")
            local_widget_ids = set()
            if os.path.isdir(local_widgets_dir):
                for wd in os.listdir(local_widgets_dir):
                    wm = os.path.join(local_widgets_dir, wd, "widget.json")
                    if os.path.exists(wm):
                        try:
                            with open(wm, 'r') as wf:
                                local_widget_ids.add(json.load(wf).get("meta", {}).get("id", ""))
                        except Exception:
                            pass
            missing_deps = []
            for comp_id in composed_ids:
                in_library = any(w['id'] == comp_id for w in self.widgets)
                in_local = comp_id in local_widget_ids
                if not in_library and not in_local:
                    missing_deps.append(comp_id)

            deps_ok = len(missing_deps) == 0
            if not check(f"All composed_of widgets exist in library or local widgets/ ({len(composed_ids)} total)", deps_ok,
                         f"Missing dependencies: {', '.join(missing_deps)}"):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": f"Dependency error: Widget '{missing_deps[0]}' not found in library. Register it first!"}

            # 7b. integration_guide structure validation
            guide = data.get("integration_guide", {})
            has_guide = bool(guide)
            check("integration_guide present", has_guide, "Blueprints require an integration_guide section")

            if has_guide:
                has_usage = "usage" in guide
                check("integration_guide.usage present", has_usage, "Missing integration_guide.usage")

                has_wiring = "runtime_wiring" in guide
                check("integration_guide.runtime_wiring present", has_wiring,
                      "Missing integration_guide.runtime_wiring - blueprints need step-by-step wiring instructions")

                if has_wiring:
                    wiring = guide.get("runtime_wiring", {})
                    has_steps = "steps" in wiring and len(wiring.get("steps", [])) > 0
                    check("runtime_wiring.steps defined", has_steps,
                          "Missing runtime_wiring.steps - add step-by-step widget instantiation guide")

        # 8. Test files follow naming convention (widgets only - blueprints don't have tests)
        test_files = []
        if item_type == "widget":
            # Python/JS/TS: test_*.py, test_*.js, test_*.ts
            # Go: *_test.go
            # Rust: *.rs in tests/ directory
            test_files = glob.glob(os.path.join(path, "tests", "test_*.*"))
            test_files += glob.glob(os.path.join(path, "tests", "*_test.go"))  # Go pattern
            test_files += glob.glob(os.path.join(path, "tests", "*.rs"))  # Rust integration tests
            test_files = list(set(test_files))  # Remove duplicates
            if not check(f"Test files found ({len(test_files)} total)", len(test_files) > 0,
                         "No test files found in tests/ directory"):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "No test files found in tests/"}

        # 8.5 & 9. Language-specific dependency install + test execution
        from languages import get_engine

        tests_passed = True
        test_error = None
        failed_test = "System"

        if item_type == "widget":
            language = data.get("tech_stack", {}).get("language", "python").lower()
            dependencies = data.get("tech_stack", {}).get("dependencies", [])

            # Validate required project files for compiled languages
            if language == "go" and not os.path.exists(os.path.join(path, "go.mod")):
                check("go.mod exists for Go widget", False,
                      "Go widgets require a go.mod file. Run 'go mod init <module-name>' in widget directory.")
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "Go widgets require a go.mod file. Add go.mod to your widget."}

            if language == "rust" and not os.path.exists(os.path.join(path, "Cargo.toml")):
                check("Cargo.toml exists for Rust widget", False,
                      "Rust widgets require a Cargo.toml file. Run 'cargo init' in widget directory.")
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "Rust widgets require a Cargo.toml file. Add Cargo.toml to your widget."}

            engine = get_engine(language)
            if engine is None:
                print(f"   ⚠️ No engine for language '{language}' — skipping dep install and tests.")
            else:
                print(f"\n📦 Installing dependencies for {item_type}...")
                try:
                    engine.install_deps(path, dependencies)
                    print("   ✅ Dependencies installed")
                except Exception as e:
                    print(f"   ⚠️ Warning: Failed to install some dependencies: {e}")

                print(f"\n🧪 Running tests for {item_type}...")
                result = engine.run_tests(path)
                if not result["passed"]:
                    tests_passed = False
                    test_error = result.get("error", "Unknown error")

                # Give JS engine a chance to clean up node_modules etc.
                if hasattr(engine, "cleanup"):
                    engine.cleanup(path)

        if not check("All tests pass", tests_passed, f"Test failure in {failed_test}: {test_error}"):
            self._print_checklist(checklist, errors, failed=True)
            # Include actual error output so AI agents can self-correct
            error_detail = str(test_error or "Unknown error")[:3000]  # Cap at 3000 chars
            return {
                "status": "error",
                "message": f"Smoke tests failed in {failed_test}. Fix errors before checkin.",
                "failed_test": failed_test,
                "test_output": error_detail
            }

        # 10. Maturity level validation (stable requires tests)
        maturity = meta.get("maturity", "prototype")
        if maturity == "stable":
            has_tests = len(test_files) > 0
            if not check("Maturity 'stable' requires passing tests", has_tests,
                         "Cannot mark as 'stable' without tests - use 'beta' instead"):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": "Widgets marked 'stable' must have tests. Change maturity to 'beta' or add tests."}
        else:
            check(f"Maturity level is '{maturity}'", True)

        # 11. Implementation Uniqueness (Warning only in validation, hard-blocked in register)
        if item_type == "widget":
            current_hash = self._calculate_implementation_hash(path)
            exact_duplicate = next((w for w in self.widgets if w.get('implementation_hash') == current_hash), None)
            check("Implementation is unique", exact_duplicate is None, 
                  f"WARNING: Identical code exists in library: {exact_duplicate['id']}" if exact_duplicate else None)
        else: # blueprint
            current_components = set(self._extract_composed_ids(data.get("composed_of", [])))
            exact_blueprint = next((w for w in self.widgets if w['type'] == 'blueprint' and set(self._extract_composed_ids(w.get('composed_of', []))) == current_components), None)
            check("Blueprint composition is unique", exact_blueprint is None,
                  f"WARNING: Blueprint with identical components exists: {exact_blueprint['id']}" if exact_blueprint else None)

        # 12. Changes detected (for existing items)
        existing_item = next((w for w in self.widgets if w['id'] == meta.get('id')), None)
        if existing_item:
            current_hash = self._calculate_implementation_hash(path)
            is_identical = False
            if item_type == "widget":
                lib_hash = existing_item.get('implementation_hash')
                is_identical = (current_hash == lib_hash)
            else: # blueprint
                lib_hash = self._calculate_implementation_hash(existing_item['path'])
                lib_components = set(self._extract_composed_ids(existing_item.get("composed_of", [])))
                curr_components = set(self._extract_composed_ids(data.get("composed_of", [])))
                is_identical = (current_hash == lib_hash and lib_components == curr_components)
            
            check("Changes detected vs library version", True, 
                  "Note: Implementation is identical to the library version." if is_identical else None)

        # Success!
        self._print_checklist(checklist, errors, failed=False)
        return {"status": "success", "message": f"{item_type.capitalize()} meets the Gold Standard"}

    def _print_checklist(self, checklist, errors, failed, test_output=None):
        """Print validation checklist with clear pass/fail status."""
        print("\n" + "=" * 60)
        if failed:
            print("❌ VALIDATION FAILED")
        else:
            print("✅ VALIDATION PASSED")
        print("=" * 60)

        for item in checklist:
            print(f"  {item}")

        if errors:
            print("\n" + "-" * 60)
            print("ERRORS:")
            for i, error in enumerate(errors, 1):
                print(f"  {i}. {error}")

        if test_output:
            print("\n" + "-" * 60)
            print("TEST OUTPUT:")
            # Truncate very long output
            if len(test_output) > 500:
                print(test_output[:500] + "\n... (output truncated)")
            else:
                print(test_output)

        print("=" * 60 + "\n")

    def checkin_item(self, path, differentiation="", update=True, reason="", version_bump="minor"):
        from checkin import checkin_item
        return checkin_item(self, path, differentiation=differentiation, update=update,
                            reason=reason, version_bump=version_bump)
    def restore(self, item_id, version, reason):
        from checkin import restore
        return restore(self, item_id, version, reason)
    def add_review(self, item_id_or_path, rating, comment, author="AI", version=None):
        from checkin import add_review
        return add_review(self, item_id_or_path, rating, comment, author=author, version=version)
    def compare_versions(self, item_id):
        from checkin import compare_versions
        return compare_versions(self, item_id)
    def compare_all_installed(self):
        from checkin import compare_all_installed
        return compare_all_installed(self)
    def _copy_widget_files(self, item_path, dest_path, widget, is_blueprint):
        from installer import _copy_widget_files
        return _copy_widget_files(self, item_path, dest_path, widget, is_blueprint)
    def install(self, widget_id, target_dir, version=None, visited=None, blueprint=None):
        from installer import install
        return install(self, widget_id, target_dir, version=version,
                       visited=visited, blueprint=blueprint)
    def uninstall(self, widget_id):
        from installer import uninstall
        return uninstall(self, widget_id)
