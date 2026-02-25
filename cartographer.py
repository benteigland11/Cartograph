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
        """Returns the most installed widgets and blueprints."""
        # Sort widgets by install_count descending
        sorted_widgets = sorted(self.widgets, key=lambda x: x.get('install_count', 0), reverse=True)
        
        return {
            "top_assets": [
                {
                    "id": w['id'],
                    "name": w['name'],
                    "version": w['version'],
                    "install_count": w.get('install_count', 0),
                    "type": w.get('type', 'widget'),
                    "maturity": w.get('maturity', 'unknown')
                } for w in sorted_widgets[:limit]
            ]
        }

    def inspect(self, widget_id, show_examples=False, show_source=False, show_tests=False, version=None):
        """Returns metadata and optionally examples/source/tests without installing."""
        widget = next((w for w in self.widgets if w['id'] == widget_id), None)
        if not widget:
            return {"error": "Widget not found"}

        # Base metadata (exclude internal path)
        result = {k: v for k, v in widget.items() if k != 'path'}
        
        # Override path if version specified
        widget_path = widget['path']
        if version:
            history_path = os.path.join(widget_path, "history", version)
            if os.path.exists(history_path):
                print(f"📜 Inspecting historical v{version} for {widget_id}", file=sys.stderr)
                widget_path = history_path
                # Update metadata for the historical version
                manifest_name = "blueprint.json" if widget['type'] == 'blueprint' else "widget.json"
                try:
                    with open(os.path.join(widget_path, manifest_name), 'r') as f:
                        hist_manifest = json.load(f)
                        result['metadata_v' + version] = hist_manifest
                except:
                    pass
            else:
                return {"error": f"Version '{version}' not found in history for {widget_id}"}
        
        # List history (always show full history even when inspecting a specific version)
        history_dir = os.path.join(widget['path'], "history")
        if os.path.exists(history_dir):
            result['history'] = os.listdir(history_dir)

        # Load changelog
        changelog_path = os.path.join(widget['path'], "changelog.json")
        if os.path.exists(changelog_path):
            try:
                with open(changelog_path, 'r') as f:
                    result['changelog'] = json.load(f)
            except:
                pass

        # Add file statistics for the selected version
        result['stats'] = {
            'files': {
                'src': len(glob.glob(os.path.join(widget_path, 'src', '*.*'))),
                'tests': len(glob.glob(os.path.join(widget_path, 'tests', '*.*'))),
                'examples': len(glob.glob(os.path.join(widget_path, 'examples', '*.*')))
            }
        }

        # Calculate lines of code in src/
        src_files = glob.glob(os.path.join(widget_path, 'src', '*.*'))
        total_lines = 0
        for src_file in src_files:
            try:
                with open(src_file, 'r') as f:
                    total_lines += len(f.readlines())
            except:
                pass
        result['stats']['lines_of_code'] = total_lines

        # Show what flags are available if none selected
        if not (show_examples or show_source or show_tests):
            result['hint'] = "Use --examples, --source, --tests, or --all for more details"
            return result

        # Show examples
        if show_examples:
            examples_dir = os.path.join(widget_path, 'examples')
            examples = {}
            if os.path.exists(examples_dir):
                example_files = glob.glob(os.path.join(examples_dir, '*.*'))
                for ex_file in example_files:
                    try:
                        with open(ex_file, 'r') as f:
                            examples[os.path.basename(ex_file)] = f.read()
                    except Exception as e:
                        examples[os.path.basename(ex_file)] = f"Error reading file: {e}"
            result['examples'] = examples if examples else {"note": "No example files found"}

        # Show source
        if show_source:
            src_dir = os.path.join(widget_path, 'src')
            source = {}
            if os.path.exists(src_dir):
                src_files = glob.glob(os.path.join(src_dir, '*.*'))
                for src_file in src_files:
                    try:
                        with open(src_file, 'r') as f:
                            source[os.path.basename(src_file)] = f.read()
                    except Exception as e:
                        source[os.path.basename(src_file)] = f"Error reading file: {e}"
            result['source'] = source if source else {"note": "No source files found"}

        # Show tests
        if show_tests:
            tests_dir = os.path.join(widget_path, 'tests')
            tests = {}
            if os.path.exists(tests_dir):
                test_files = glob.glob(os.path.join(tests_dir, '*.*'))
                for t_file in test_files:
                    try:
                        with open(t_file, 'r') as f:
                            tests[os.path.basename(t_file)] = f.read()
                    except Exception as e:
                        tests[os.path.basename(t_file)] = f"Error reading file: {e}"
            result['tests'] = tests if tests else {"note": "No test files found"}

        return result


    def _log_registration(self, widget_id, widget_name, similar_widgets, differentiation, needs_review, widget_path):
        """Log widget registration for audit trail."""
        import datetime

        # Ensure .cartographer directory exists
        os.makedirs(CARTOGRAPHER_DIR, exist_ok=True)

        # Load existing log
        log = {"extractions": []}
        if os.path.exists(EXTRACTION_LOG_PATH):
            try:
                with open(EXTRACTION_LOG_PATH, 'r') as f:
                    log = json.load(f)
            except:
                pass

        # Add new entry
        log["extractions"].append({
            "widget_id": widget_id,
            "widget_name": widget_name,
            "timestamp": datetime.datetime.now().isoformat(),
            "needs_review": needs_review,
            "similar_widgets_found": [
                {"id": w["id"], "relevance_score": w["relevance_score"]}
                for w in similar_widgets
            ],
            "differentiation": differentiation or None,
            "widget_path": widget_path
        })

        # Save log
        with open(EXTRACTION_LOG_PATH, 'w') as f:
            json.dump(log, f, indent=2)

    def review_pending_widgets(self):
        """Interactive review of pending widgets."""

        # Check if pending directory exists
        if not os.path.exists(PENDING_WIDGETS_PATH):
            print("✅ No pending widgets to review!")
            return

        # Find all pending widgets
        pending_widgets = []
        for item in os.listdir(PENDING_WIDGETS_PATH):
            widget_path = os.path.join(PENDING_WIDGETS_PATH, item)
            if os.path.isdir(widget_path):
                manifest_path = os.path.join(widget_path, "widget.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r') as f:
                            data = json.load(f)
                            pending_widgets.append({
                                "folder": item,
                                "path": widget_path,
                                "manifest": data
                            })
                    except:
                        continue

        if not pending_widgets:
            print("✅ No pending widgets to review!")
            return

        print(f"\n📋 Found {len(pending_widgets)} pending widget(s)\n")
        print("=" * 80)

        for idx, widget in enumerate(pending_widgets, 1):
            meta = widget["manifest"].get("meta", {})
            widget_id = meta.get("id", "unknown")
            widget_name = meta.get("name", "Unknown")
            differentiation = meta.get("differentiation", "")
            similar_widgets = meta.get("similar_widgets", [])

            print(f"\n[{idx}/{len(pending_widgets)}] {widget_name} ({widget_id})")
            print("-" * 80)

            if similar_widgets:
                print(f"\n⚠️  Similar to existing widgets:")
                for sim_id in similar_widgets:
                    # Try to find the widget in our library
                    sim_widget = next((w for w in self.widgets if w['id'] == sim_id), None)
                    if sim_widget:
                        print(f"  • {sim_id}")
                        print(f"    {sim_widget['description'][:70]}...")
                        print(f"    Maturity: {sim_widget.get('maturity', 'unknown')}")
                    else:
                        print(f"  • {sim_id}")

            if differentiation:
                print(f"\n💡 Differentiation: {differentiation}")

            print(f"\n📁 Location: {widget['path']}")

            # Prompt for action
            while True:
                choice = input("\n❓ Action: [a]pprove  [r]eject  [i]nspect  [s]kip  [q]uit: ").strip().lower()

                if choice == 'a':
                    self._approve_widget(widget)
                    break
                elif choice == 'r':
                    self._reject_widget(widget)
                    break
                elif choice == 'i':
                    print("\n" + json.dumps(widget["manifest"], indent=2))
                elif choice == 's':
                    print("⏭️  Skipped")
                    break
                elif choice == 'q':
                    print("\n👋 Review session ended")
                    return
                else:
                    print("Invalid choice. Please choose a, r, i, s, or q.")

            print("\n" + "=" * 80)

        print("\n✅ Review complete!")

    def _approve_widget(self, widget):
        """Approve a pending widget - move to Widget_Library."""
        folder_name = widget["folder"]
        source_path = widget["path"]
        dest_path = os.path.join(self.library_path, folder_name)

        # Ensure destination doesn't exist
        if os.path.exists(dest_path):
            print(f"❌ Error: Widget already exists in library: {dest_path}")
            return

        # Update manifest to remove needs_review flag
        manifest_path = os.path.join(source_path, "widget.json")
        data = widget["manifest"]
        if "needs_review" in data.get("meta", {}):
            data["meta"]["needs_review"] = False
            with open(manifest_path, 'w') as f:
                json.dump(data, f, indent=2)

        # Move to Widget_Library
        shutil.move(source_path, dest_path)
        print(f"✅ Approved! Moved to Widget_Library/{folder_name}")
        print(f"   Widget is now searchable")

    def _reject_widget(self, widget):
        """Reject a pending widget - delete it."""
        widget_id = widget["manifest"].get("meta", {}).get("id", "unknown")
        confirm = input(f"⚠️  Delete {widget_id} permanently? [y/N]: ").strip().lower()

        if confirm == 'y':
            shutil.rmtree(widget["path"])
            print(f"🗑️  Deleted {widget_id}")
        else:
            print("❌ Cancelled")

    def create(self, item_id, language=None, name=None, domain="backend", tags=None,
                target_dir=None, item_type="widget", composed_of=None, gpu_targets=None, widget_type=None):
        from scaffolding import create_widget, create_blueprint
        if item_type == "blueprint":
            return create_blueprint(self, item_id, name=name, domain=domain, tags=tags,
                                    target_dir=target_dir, composed_of=composed_of)
        return create_widget(self, item_id, language=language, name=name, domain=domain,
                             tags=tags, target_dir=target_dir, gpu_targets=gpu_targets,
                             widget_type=widget_type)
    def _create_hip_files(self, target_dir, module_name, display_name, gpu_targets=None):
        """Create HIP kernel widget scaffold with Python test harness."""
        targets_str = ", ".join(gpu_targets) if gpu_targets else "gfx1100"
        first_target = gpu_targets[0] if gpu_targets else "gfx1100"

        with open(os.path.join(target_dir, "src", f"{module_name}.hip"), 'w') as f:
            f.write(f'''#include <hip/hip_runtime.h>
#include "{module_name}.h"

/// {display_name}: GPU kernel
__global__ void {module_name}_kernel(float* output, const float* input, int n) {{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {{
        output[idx] = input[idx];
    }}
}}

void {module_name}_launch(float* output, const float* input, int n, hipStream_t stream) {{
    int block_size = 256;
    int grid_size = (n + block_size - 1) / block_size;
    hipLaunchKernelGGL({module_name}_kernel, dim3(grid_size), dim3(block_size), 0, stream,
                       output, input, n);
}}
''')
        with open(os.path.join(target_dir, "src", f"{module_name}.h"), 'w') as f:
            f.write(f'''#pragma once
#include <hip/hip_runtime.h>

/// {display_name}: host-side launch wrapper
void {module_name}_launch(float* output, const float* input, int n, hipStream_t stream = 0);
''')
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), 'w') as f:
            f.write(f'''"""Test harness for {display_name} HIP kernel.

Compiles the kernel with hipcc, loads the .so, and validates output.
Requires: hipcc, numpy. Optional: torch (for GPU tensor validation).
"""
import subprocess
import os
import sys
import tempfile

def test_{module_name}_compiles():
    """Verify the kernel compiles for target architecture."""
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
    src_file = os.path.join(src_dir, '{module_name}.hip')
    assert os.path.exists(src_file), f"Source file not found: {{src_file}}"

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, '{module_name}.so')
        cmd = [
            'hipcc', '-O2',
            '--offload-arch={first_target}',
            '-shared', '-fPIC',
            src_file,
            '-o', out_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Compilation failed:\\n{{result.stderr}}"
        assert os.path.exists(out_file), "Output .so not produced"

if __name__ == "__main__":
    test_{module_name}_compiles()
    print("All tests passed")
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.py"), 'w') as f:
            f.write(f'''"""Example: compile and use the {display_name} HIP kernel.

Target architectures: {targets_str}
"""
import subprocess
import os

src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
src_file = os.path.join(src_dir, '{module_name}.hip')
out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')

os.makedirs(os.path.dirname(out_file), exist_ok=True)

# Compile
print(f"Compiling {{src_file}}...")
cmd = ['hipcc', '-O2', '--offload-arch={first_target}', '-shared', '-fPIC', src_file, '-o', out_file]
subprocess.run(cmd, check=True)
print(f"Built: {{out_file}}")

# To use from Python, load with ctypes:
# import ctypes
# lib = ctypes.CDLL(out_file)
''')

    def _create_cpp_files(self, target_dir, module_name, display_name):
        """Create C++ widget scaffold with Python test harness."""
        with open(os.path.join(target_dir, "src", f"{module_name}.cpp"), 'w') as f:
            f.write(f'''#include "{module_name}.h"

/// {display_name}: process a value.
int {module_name}(int value) {{
    return value;
}}
''')
        with open(os.path.join(target_dir, "src", f"{module_name}.h"), 'w') as f:
            f.write(f'''#pragma once

/// {display_name}: process a value.
int {module_name}(int value);
''')
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), 'w') as f:
            f.write(f'''"""Test harness for {display_name} C++ widget.

Compiles with g++, runs the binary, and validates output.
"""
import subprocess
import os
import tempfile

def test_{module_name}_compiles_and_runs():
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
    src_file = os.path.join(src_dir, '{module_name}.cpp')
    assert os.path.exists(src_file), f"Source not found: {{src_file}}"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a small test driver
        driver = os.path.join(tmpdir, 'driver.cpp')
        with open(driver, 'w') as f:
            f.write(\'\'\'#include <iostream>
#include "{module_name}.h"
int main() {{
    int result = {module_name}(42);
    if (result != 42) {{ std::cerr << "FAIL" << std::endl; return 1; }}
    std::cout << "PASS" << std::endl;
    return 0;
}}\'\'\')

        out_bin = os.path.join(tmpdir, 'test_bin')
        compile_cmd = ['g++', '-std=c++17', '-I', src_dir, src_file, driver, '-o', out_bin]
        res = subprocess.run(compile_cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"Compilation failed:\\n{{res.stderr}}"

        run_res = subprocess.run([out_bin], capture_output=True, text=True)
        assert run_res.returncode == 0, f"Test failed:\\n{{run_res.stderr}}"
        assert "PASS" in run_res.stdout

if __name__ == "__main__":
    test_{module_name}_compiles_and_runs()
    print("All tests passed")
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.py"), 'w') as f:
            f.write(f'''"""Example: compile and use the {display_name} C++ widget."""
import subprocess
import os

src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
src_file = os.path.join(src_dir, '{module_name}.cpp')

# Compile as shared library
out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')
os.makedirs(os.path.dirname(out_file), exist_ok=True)

subprocess.run(['g++', '-std=c++17', '-shared', '-fPIC', src_file, '-o', out_file], check=True)
print(f"Built: {{out_file}}")
''')

    def _create_c_files(self, target_dir, module_name, display_name):
        """Create C widget scaffold with Python test harness."""
        with open(os.path.join(target_dir, "src", f"{module_name}.c"), 'w') as f:
            f.write(f'''#include "{module_name}.h"

/* {display_name}: process a value. */
int {module_name}(int value) {{
    return value;
}}
''')
        with open(os.path.join(target_dir, "src", f"{module_name}.h"), 'w') as f:
            f.write(f'''#pragma once

/* {display_name}: process a value. */
int {module_name}(int value);
''')
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), 'w') as f:
            f.write(f'''"""Test harness for {display_name} C widget.

Compiles with gcc, runs the binary, and validates output.
"""
import subprocess
import os
import tempfile

def test_{module_name}_compiles_and_runs():
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
    src_file = os.path.join(src_dir, '{module_name}.c')
    assert os.path.exists(src_file), f"Source not found: {{src_file}}"

    with tempfile.TemporaryDirectory() as tmpdir:
        driver = os.path.join(tmpdir, 'driver.c')
        with open(driver, 'w') as f:
            f.write(\'\'\'#include <stdio.h>
#include "{module_name}.h"
int main() {{
    int result = {module_name}(42);
    if (result != 42) {{ fprintf(stderr, "FAIL\\n"); return 1; }}
    printf("PASS\\n");
    return 0;
}}\'\'\')

        out_bin = os.path.join(tmpdir, 'test_bin')
        compile_cmd = ['gcc', '-std=c11', '-I', src_dir, src_file, driver, '-o', out_bin]
        res = subprocess.run(compile_cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"Compilation failed:\\n{{res.stderr}}"

        run_res = subprocess.run([out_bin], capture_output=True, text=True)
        assert run_res.returncode == 0, f"Test failed:\\n{{run_res.stderr}}"
        assert "PASS" in run_res.stdout

if __name__ == "__main__":
    test_{module_name}_compiles_and_runs()
    print("All tests passed")
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.py"), 'w') as f:
            f.write(f'''"""Example: compile and use the {display_name} C widget."""
import subprocess
import os

src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
src_file = os.path.join(src_dir, '{module_name}.c')

out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')
os.makedirs(os.path.dirname(out_file), exist_ok=True)

subprocess.run(['gcc', '-std=c11', '-shared', '-fPIC', src_file, '-o', out_file], check=True)
print(f"Built: {{out_file}}")
''')

    def _create_blueprint(self, item_id, name=None, domain="backend", tags=None, target_dir=None, composed_of=None):
        """Create a new blueprint with starter files."""
        if tags is None:
            tags = []
        if composed_of is None:
            composed_of = []
        if not name:
            name = item_id.replace('-', ' ').title()

        # Default target: ./cartographer/blueprints/<item_id>/
        if not target_dir:
            target_dir = os.path.join(os.getcwd(), DEFAULT_INSTALL_DIR, "blueprints", item_id)

        if os.path.exists(target_dir):
            print(f"❌ Error: Directory already exists: {target_dir}", file=sys.stderr)
            return {"status": "error", "message": f"Directory already exists: {target_dir}"}

        print(f"✨ Creating blueprint '{item_id}' in {target_dir}...", file=sys.stderr)

        os.makedirs(target_dir)
        os.makedirs(os.path.join(target_dir, "src"))
        os.makedirs(os.path.join(target_dir, "examples"))
        os.makedirs(os.path.join(target_dir, "widgets"))

        # Build pinned composed_of from widget IDs
        pinned_composed = []
        for wid in composed_of:
            widget = next((w for w in self.widgets if w['id'] == wid), None)
            if widget:
                pinned_composed.append({"id": wid, "version": widget.get("version", "1.0.0")})
            else:
                pinned_composed.append({"id": wid, "version": None})

        # Generate blueprint.json
        manifest = {
            "meta": {
                "id": item_id,
                "name": name,
                "version": "1.0.0",
                "type": "blueprint",
                "domain": domain,
                "tags": tags,
                "maturity": "beta"
            },
            "composed_of": pinned_composed,
            "configuration": {},
            "description": f"{name} blueprint",
            "integration_guide": {
                "pattern": "dependency_injection",
                "usage": "Install widgets into this blueprint, then wire them together in src/",
                "runtime_wiring": {
                    "description": "Wire up the workflow after installation",
                    "prerequisites": {"environment": [], "database": [], "application": []},
                    "steps": []
                }
            }
        }
        with open(os.path.join(target_dir, "blueprint.json"), 'w') as f:
            json.dump(manifest, f, indent=2)

        # Create placeholder example
        with open(os.path.join(target_dir, "examples", "basic_usage.md"), 'w') as f:
            f.write(f"# {name} Blueprint\n\n"
                    f"## Usage\n\n"
                    f"1. Install widgets into this blueprint using `cartographer_install` with the `blueprint` parameter.\n"
                    f"2. Wire the widgets together in `src/`.\n"
                    f"3. Check in the self-contained blueprint.\n")

        # Create src/workflow.py with import pattern documentation
        class_name = name.replace(' ', '')
        with open(os.path.join(target_dir, "src", "workflow.py"), 'w') as f:
            f.write(f'''"""
{name} Blueprint Workflow

Wire your installed widgets together here.

IMPORTING FROM COMPOSED WIDGETS
===============================
Widgets live in ../widgets/<widget_id>/src/. There are two patterns
depending on whether the widget's src/ is a flat module or a package
(has __init__.py with relative imports).

Pattern 1 — Flat modules (no __init__.py, or __init__.py without relative imports):
    import sys, os
    widget_src = os.path.join(os.path.dirname(__file__), '..', 'widgets', '<widget_id>', 'src')
    sys.path.insert(0, widget_src)
    from module_name import some_function

Pattern 2 — Packages with __init__.py and relative imports (use importlib):
    import importlib, sys, os

    def _load_widget(widget_id, package_alias=None):
        \\"\\"\\"Load a widget's src/ as a Python package, aliased to avoid collisions.\\"\\"\\"
        alias = package_alias or widget_id.replace('-', '_')
        widget_src = os.path.join(os.path.dirname(__file__), '..', 'widgets', widget_id, 'src')
        parent_dir = os.path.join(os.path.dirname(__file__), '..', 'widgets', widget_id)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        mod = importlib.import_module('src')
        sys.modules[alias] = mod
        if 'src' in sys.modules and sys.modules['src'] is mod:
            del sys.modules['src']
        return mod

    # Example: load two widgets without 'src' namespace collision
    retry = _load_widget('logic-retry-backoff-python', 'retry')
    auth  = _load_widget('logic-cognitoauth-python', 'auth')

    # Now use them:
    retry.retry_with_backoff(...)
    auth.authenticate(...)

Pick the simplest pattern that works for your widgets. Most widgets
use flat modules (Pattern 1). Use Pattern 2 only when you see
ImportError from relative imports in __init__.py.
"""
import os
import sys


class {class_name}Workflow:
    def __init__(self):
        pass

    def run(self):
        raise NotImplementedError('Wire up your widgets here')
''')

        print(f"✅ Created blueprint: {target_dir}", file=sys.stderr)
        return {"status": "success", "path": target_dir, "item_id": item_id, "type": "blueprint"}

    # --- Language-specific file generators ---

    def _create_python_files(self, target_dir, module_name, display_name):
        with open(os.path.join(target_dir, "src", "__init__.py"), 'w') as f:
            f.write(f"from .{module_name} import {module_name}\n")
        with open(os.path.join(target_dir, "src", f"{module_name}.py"), 'w') as f:
            f.write(f'''def {module_name}(value):
    """{display_name}: process a value."""
    return value
''')
        with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), 'w') as f:
            f.write(f'''import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from {module_name} import {module_name}


def test_{module_name}_returns_value():
    assert {module_name}(42) == 42
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.py"), 'w') as f:
            f.write(f'''import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from {module_name} import {module_name}

result = {module_name}("hello")
print(f"Result: {{result}}")
''')

    def _create_javascript_files(self, target_dir, module_name, display_name, item_id):
        func_name = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), module_name)
        with open(os.path.join(target_dir, "src", "index.js"), 'w') as f:
            f.write(f'''/**
 * {display_name}: process a value.
 * @param {{*}} value
 * @returns {{*}}
 */
export function {func_name}(value) {{
  return value;
}}
''')
        with open(os.path.join(target_dir, "tests", "test_index.js"), 'w') as f:
            f.write(f'''import {{ describe, it, expect }} from 'vitest';
import {{ {func_name} }} from '../src/index.js';

describe('{func_name}', () => {{
  it('should return the value', () => {{
    expect({func_name}(42)).toBe(42);
  }});
}});
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.js"), 'w') as f:
            f.write(f'''import {{ {func_name} }} from '../src/index.js';

const result = {func_name}('hello');
console.log('Result:', result);
''')
        with open(os.path.join(target_dir, "package.json"), 'w') as f:
            json.dump({
                "name": item_id,
                "version": "1.0.0",
                "type": "module",
                "scripts": {"test": "vitest run"},
                "devDependencies": {"vitest": "^1.0.0"}
            }, f, indent=2)

    def _create_typescript_files(self, target_dir, module_name, display_name, item_id):
        func_name = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), module_name)
        with open(os.path.join(target_dir, "src", "index.ts"), 'w') as f:
            f.write(f'''/**
 * {display_name}: process a value.
 */
export function {func_name}(value: unknown): unknown {{
  return value;
}}
''')
        with open(os.path.join(target_dir, "tests", "test_index.ts"), 'w') as f:
            f.write(f'''import {{ describe, it, expect }} from 'vitest';
import {{ {func_name} }} from '../src/index';

describe('{func_name}', () => {{
  it('should return the value', () => {{
    expect({func_name}(42)).toBe(42);
  }});
}});
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.ts"), 'w') as f:
            f.write(f'''import {{ {func_name} }} from '../src/index';

const result = {func_name}('hello');
console.log('Result:', result);
''')
        with open(os.path.join(target_dir, "package.json"), 'w') as f:
            json.dump({
                "name": item_id,
                "version": "1.0.0",
                "type": "module",
                "scripts": {"test": "vitest run"},
                "devDependencies": {"vitest": "^1.0.0", "typescript": "^5.0.0"}
            }, f, indent=2)
        with open(os.path.join(target_dir, "tsconfig.json"), 'w') as f:
            json.dump({
                "compilerOptions": {
                    "target": "ES2020",
                    "module": "ESNext",
                    "moduleResolution": "bundler",
                    "strict": True,
                    "outDir": "dist",
                    "rootDir": "src"
                },
                "include": ["src"]
            }, f, indent=2)

    def _create_go_files(self, target_dir, module_name, display_name, item_id):
        pkg_name = module_name.replace('_', '').lower()
        func_name = module_name.replace('_', ' ').title().replace(' ', '')
        with open(os.path.join(target_dir, "src", f"{module_name}.go"), 'w') as f:
            f.write(f'''package {pkg_name}

// {func_name} processes a value.
func {func_name}(value string) string {{
\treturn value
}}
''')
        with open(os.path.join(target_dir, "tests", f"{module_name}_test.go"), 'w') as f:
            f.write(f'''package {pkg_name}

import "testing"

func Test{func_name}(t *testing.T) {{
\tresult := {func_name}("hello")
\tif result != "hello" {{
\t\tt.Errorf("expected hello, got %s", result)
\t}}
}}
''')
        with open(os.path.join(target_dir, "examples", "example_test.go"), 'w') as f:
            f.write(f'''package {pkg_name}_test

import "fmt"

func Example{func_name}() {{
\t// result := {pkg_name}.{func_name}("hello")
\tfmt.Println("hello")
\t// Output: hello
}}
''')
        with open(os.path.join(target_dir, "go.mod"), 'w') as f:
            f.write(f"module {item_id}\n\ngo 1.21\n")

    def _create_rust_files(self, target_dir, module_name, display_name, item_id):
        func_name = module_name
        crate_name = item_id.replace('-', '_') if item_id else module_name
        with open(os.path.join(target_dir, "src", "lib.rs"), 'w') as f:
            f.write(f'''/// {display_name}: process a value.
pub fn {func_name}(value: &str) -> String {{
    value.to_string()
}}

#[cfg(test)]
mod tests {{
    use super::*;

    #[test]
    fn test_{func_name}() {{
        assert_eq!({func_name}("hello"), "hello");
    }}
}}
''')
        with open(os.path.join(target_dir, "tests", "integration_test.rs"), 'w') as f:
            f.write(f'''use {crate_name}::{func_name};

#[test]
fn test_{func_name}_integration() {{
    let result = {func_name}("world");
    assert_eq!(result, "world");
}}
''')
        with open(os.path.join(target_dir, "examples", "basic_usage.rs"), 'w') as f:
            f.write(f'''use {crate_name}::{func_name};

fn main() {{
    let result = {func_name}("hello");
    println!("Result: {{}}", result);
}}
''')
        with open(os.path.join(target_dir, "Cargo.toml"), 'w') as f:
            f.write(f'''[package]
name = "{item_id}"
version = "1.0.0"
edition = "2021"

[lib]
path = "src/lib.rs"

[[example]]
name = "basic_usage"
path = "examples/basic_usage.rs"
''')

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
