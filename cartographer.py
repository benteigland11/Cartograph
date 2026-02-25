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
    def __init__(self, library_path, blueprint_path=None, search_backend='hybrid'):
        self.library_path = library_path
        self.blueprint_path = blueprint_path
        self.widgets = []
        self.install_stats = self._load_install_stats()
        self.installed_index = self._load_installed_index()
        self._load_library()
        if self.blueprint_path:
            self._load_blueprints()

        from search import get_backend
        backend_name = 'hybrid' if search_backend == 'meilisearch' else search_backend
        self._search_backend = get_backend(backend_name)
        self._search_backend.build(self.widgets)


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
                meta = data.get('meta', data)

                widget_path = os.path.dirname(manifest_path)
                item_id = meta.get('id', os.path.basename(widget_path))
                tags = meta.get('tags', [])
                desc = data.get('description', '')

                # Compute stats at load time (not stored in manifest)
                test_count = self._count_tests(widget_path)
                review_data = self._load_reviews(widget_path)
                implementation_hash = self._calculate_implementation_hash(widget_path)

                total_lines = 0
                src_dir = os.path.join(widget_path, "src")
                if os.path.exists(src_dir):
                    for src_file in glob.glob(os.path.join(src_dir, "*.*")):
                        try:
                            total_lines += len(open(src_file).read().splitlines())
                        except Exception:
                            pass

                self.widgets.append({
                    "id": item_id,
                    "name": meta.get('name', 'Unknown Widget'),
                    "version": meta.get('version', '1.0.0'),
                    "type": "widget",
                    "path": widget_path,
                    "tags": tags,
                    "domain": meta.get('domain', 'universal').lower(),
                    "description": desc,
                    "language": data.get('tech_stack', {}).get('language', 'unknown'),
                    "dependencies": data.get('tech_stack', {}).get('dependencies', []),
                    "implementation_hash": implementation_hash,
                    "installed_at": self._get_installed_info(item_id),
                    "is_installed": bool(self._get_installed_info(item_id)),
                    "install_count": self._get_install_count(item_id),
                    "rating": review_data["rating"],
                    "review_count": review_data["count"],
                    "reviews": review_data["reviews"],
                    "test_count": test_count,
                    "lines_of_code": total_lines,
                })
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
            except Exception:
                continue

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
    def create(self, item_id, language=None, name=None, domain="backend", tags=None,
                target_dir=None, item_type="widget", composed_of=None, gpu_targets=None, widget_type=None):
        from scaffolding import create_widget, create_blueprint
        if item_type == "blueprint":
            return create_blueprint(self, item_id, name=name, domain=domain, tags=tags,
                                    target_dir=target_dir, composed_of=composed_of)
        return create_widget(self, item_id, language=language, name=name, domain=domain,
                             tags=tags, target_dir=target_dir, gpu_targets=gpu_targets,
                             widget_type=widget_type)

    def search(self, query, domain_filter=None, language_filter=None, type_filter=None, top_k=15):
        """Search the widget library using hybrid BM25 + n-gram fuzzy matching."""
        return self._search_backend.query(
            query,
            domain_filter=domain_filter,
            language_filter=language_filter,
            type_filter=type_filter,
            top_k=top_k,
        )

    _VALID_DOMAINS = frozenset([
        "backend", "data", "ml", "security", "infra", "frontend", "universal"
    ])

    def validate_item(self, path):
        """Validate a Python widget directory before checkin."""
        checklist = []
        errors = []

        def check(description, passed, error_detail=None):
            checklist.append(f"{'✅' if passed else '❌'} {description}")
            if not passed and error_detail:
                errors.append(error_detail)
            return passed

        # 1. Path exists
        if not check("Path exists", os.path.exists(path), f"Path not found: {path}"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Path not found: {path}"}

        # 2. widget.json exists
        manifest_path = os.path.join(path, "widget.json")
        if not os.path.exists(manifest_path):
            if os.path.exists(os.path.join(path, "blueprint.json")):
                return {"status": "error", "message": "Blueprint validation is not supported in v0.1."}
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Missing widget.json"}

        check("widget.json exists", True)

        # 3. Valid JSON, no TODOs
        try:
            content = open(manifest_path).read()
            data = json.loads(content)
            check("widget.json is valid JSON", True)
        except Exception as e:
            check("widget.json is valid JSON", False, str(e))
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Invalid JSON: {e}"}

        todo_count = content.count("[TODO]")
        if not check("No [TODO] placeholders", todo_count == 0,
                     f"Found {todo_count} [TODO] placeholder(s) — fill them in"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Replace all [TODO] placeholders in widget.json"}

        # 4. Required meta fields
        meta = data.get("meta", {})
        for field in ("id", "name", "domain"):
            if not check(f"meta.{field} present", bool(meta.get(field)),
                         f"Missing required field meta.{field}"):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": f"meta.{field} is required"}

        # 5. Domain is a known value
        domain = meta.get("domain", "").lower()
        valid_domains = sorted(self._VALID_DOMAINS)
        if not check(f"meta.domain is valid ({domain})",
                     domain in self._VALID_DOMAINS,
                     f"'{domain}' is not a valid domain. Choose one of: {', '.join(valid_domains)}"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error",
                    "message": f"Invalid domain '{domain}'. Valid domains: {', '.join(valid_domains)}"}

        # 6. tech_stack
        tech_stack = data.get("tech_stack", {})
        if not check("tech_stack.language present", bool(tech_stack.get("language")),
                     "Missing tech_stack.language"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Missing tech_stack.language"}

        if not check("tech_stack.dependencies present", "dependencies" in tech_stack,
                     "Missing tech_stack.dependencies (use [] if none)"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Missing tech_stack.dependencies"}

        # 7. Required structure: src/, tests/, examples/
        for folder in ("src", "tests", "examples"):
            folder_path = os.path.join(path, folder)
            ok = os.path.isdir(folder_path) and bool(os.listdir(folder_path))
            if not check(f"{folder}/ exists and has files", ok,
                         f"{folder}/ is missing or empty"):
                self._print_checklist(checklist, errors, failed=True)
                return {"status": "error", "message": f"{folder}/ is missing or empty"}

        # 7b. example_usage.py exists, has no TODOs, and runs cleanly
        example_path = os.path.join(path, "examples", "example_usage.py")
        if not check("examples/example_usage.py exists", os.path.exists(example_path),
                     "Missing examples/example_usage.py"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Missing examples/example_usage.py"}

        example_content = open(example_path).read()
        example_todos = example_content.count("[TODO]")
        if not check("No [TODO] in example_usage.py", example_todos == 0,
                     f"Found {example_todos} [TODO] placeholder(s) in example_usage.py — write real example code"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "Replace [TODO] placeholders in examples/example_usage.py"}

        import subprocess
        example_result = subprocess.run(
            [sys.executable, "examples/example_usage.py"],
            cwd=path, capture_output=True, text=True, timeout=15
        )
        example_ok = example_result.returncode == 0
        example_err = (example_result.stderr or example_result.stdout)[:500]
        if not check("example_usage.py runs cleanly", example_ok, example_err):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "example_usage.py failed to run.",
                    "test_output": example_err}

        # 8. Test files follow naming convention
        test_files = glob.glob(os.path.join(path, "tests", "test_*.py"))
        if not check(f"Test files found ({len(test_files)})", len(test_files) > 0,
                     "No test_*.py files found in tests/"):
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": "No test_*.py files found in tests/"}

        # 9. Install deps and run tests
        from languages import get_engine
        language = tech_stack.get("language", "python").lower()
        dependencies = tech_stack.get("dependencies", [])
        engine = get_engine(language)

        if engine is None:
            check(f"Language '{language}' recognised", False, f"Unknown language '{language}'")
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Unknown language '{language}'"}

        print(f"\n🔍 Running language checks...")
        lang_check = engine.validate_widget(path, dependencies)
        if not check("Language checks pass", lang_check["passed"],
                     lang_check.get("error", "")):
            self._print_checklist(checklist, errors, failed=True,
                                  test_output=lang_check.get("error"))
            return {"status": "error", "message": lang_check.get("error", "Language checks failed"),
                    "test_output": lang_check.get("error", "")}

        print(f"\n📦 Installing dependencies...")
        try:
            engine.install_deps(path, dependencies)
            check("Dependencies installed", True)
        except Exception as e:
            check("Dependencies installed", False, str(e))
            self._print_checklist(checklist, errors, failed=True)
            return {"status": "error", "message": f"Dependency install failed: {e}"}

        print(f"\n🧪 Running tests...")
        result = engine.run_tests(path)
        test_error = result.get("error", "")
        if not check("All tests pass", result["passed"], test_error):
            self._print_checklist(checklist, errors, failed=True, test_output=test_error)
            return {"status": "error", "message": "Tests failed. Fix before checkin.",
                    "test_output": test_error[:3000]}

        # 10. Uniqueness check
        current_hash = self._calculate_implementation_hash(path)
        duplicate = next((w for w in self.widgets
                          if w.get("implementation_hash") == current_hash
                          and w["id"] != meta.get("id")), None)
        check("Implementation is unique",
              duplicate is None,
              f"Identical code already exists: {duplicate['id']}" if duplicate else None)

        self._print_checklist(checklist, errors, failed=False)
        return {"status": "success", "message": "Widget is valid"}

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

    def checkin(self, path, reason="", version_bump="minor",
                override_warnings=False, override_reason=""):
        from checkin import checkin
        return checkin(self, path, reason=reason, version_bump=version_bump,
                       override_warnings=override_warnings, override_reason=override_reason)
    def restore(self, item_id, version, reason):
        from checkin import restore
        return restore(self, item_id, version, reason)
    def add_review(self, installed_path, rating, comment, author="AI"):
        from checkin import add_review
        return add_review(self, installed_path, rating, comment, author=author)
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
