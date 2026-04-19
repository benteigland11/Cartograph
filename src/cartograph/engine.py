import json
import os
import shutil
import glob
import re
import hashlib
import difflib
import logging

log = logging.getLogger("cartograph")


def calculate_implementation_hash(path: str) -> str | None:
    """Stable MD5 over src/, tests/, and examples/ bytes.

    Walked deterministically (sorted filenames per directory, __pycache__ and
    .pyc skipped) so the same widget contents always produce the same digest
    regardless of filesystem enumeration order. Returns None if none of the
    three directories exist.

    This is the wire-format hash — callers that want to include an
    `implementation_hash` alongside a widget payload (publish, proposals,
    inspect responses) should use this function so client and server agree on
    the bytes that were hashed.
    """
    hasher = hashlib.md5()
    found_any = False
    for subdir in ("src", "tests", "examples"):
        sub_path = os.path.join(path, subdir)
        if not os.path.exists(sub_path):
            continue
        found_any = True
        for root, dirs, files in os.walk(sub_path):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in sorted(files):
                if name.endswith('.pyc'):
                    continue
                filepath = os.path.join(root, name)
                with open(filepath, 'rb') as f:
                    hasher.update(f.read())
    if not found_any:
        return None
    return hasher.hexdigest()


def semver_key(v: str):
    """Return a sort key for a semver string using packaging.Version.
    Falls back to (0, 0, 0) for malformed strings so comparisons never crash.
    Use this everywhere versions need to be compared or sorted."""
    try:
        from packaging.version import Version
        return Version(v)
    except Exception:
        try:
            from packaging.version import Version
            return Version("0.0.0")
        except Exception:
            parts = str(v).split(".")
            try:
                return tuple(int(p) for p in parts[:3])
            except (ValueError, AttributeError):
                return (0, 0, 0)

# Package directory (src/cartograph/) — two levels up is the repo root in dev
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(PACKAGE_DIR))

# Seed library bundled with the package
_SEED_LIBRARY = os.path.join(PACKAGE_DIR, "seed_library")


def _user_data_dir() -> str:
    """Return the platform-appropriate user data directory for Cartograph."""
    import sys as _sys
    if _sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    elif _sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    return os.path.join(base, "cartograph")


def _ensure_library(path: str) -> None:
    """Create the library directory and seed it from bundled widgets if empty."""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    if os.path.isdir(_SEED_LIBRARY) and not any(
        e.name != ".DS_Store" for e in os.scandir(path)
    ):
        log.info("Seeding widget library from bundled defaults at %s", path)
        for item in os.listdir(_SEED_LIBRARY):
            src = os.path.join(_SEED_LIBRARY, item)
            dst = os.path.join(path, item)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.copytree(src, dst)
    _ensure_global_rules()


def _ensure_global_rules() -> None:
    """Create global rules templates for any languages that don't have one yet."""
    rules_dir = os.path.join(_user_data_dir(), "rules")
    try:
        from .rules import _LANGUAGE_RULES, get_template, get_rules_filename
        os.makedirs(rules_dir, exist_ok=True)
        for lang in _LANGUAGE_RULES:
            filename = get_rules_filename(lang)
            template = get_template(lang)
            if not filename or not template:
                continue
            filepath = os.path.join(rules_dir, filename)
            if not os.path.exists(filepath):
                with open(filepath, "w") as f:
                    f.write(template)
    except Exception as e:
        log.debug("Could not create global rules templates: %s", e)


def _resolve_library_path() -> str:
    """Resolve widget library path: env var > user data dir > dev repo sibling."""
    if "WIDGET_LIBRARY_PATH" in os.environ:
        _ensure_global_rules()
        return os.environ["WIDGET_LIBRARY_PATH"]
    # Dev: repo sibling takes priority over user data dir so local edits work
    _repo_lib = os.path.join(REPO_DIR, "Widget_Library")
    if os.path.exists(_repo_lib):
        _ensure_global_rules()
        return _repo_lib
    # Normal install: use platform user data dir, seeding if needed
    user_lib = os.path.join(_user_data_dir(), "Widget_Library")
    _ensure_library(user_lib)  # _ensure_library calls _ensure_global_rules internally
    return user_lib


LIBRARY_PATH = _resolve_library_path()

CARTOGRAPH_DIR = os.path.join(_user_data_dir(), ".state")
INSTALL_STATS_PATH = os.path.join(CARTOGRAPH_DIR, "stats.json")
LIBRARY_CACHE_PATH = os.path.join(CARTOGRAPH_DIR, "library_cache.json")

DEFAULT_INSTALL_DIR = "cg"

# Canonical language alias map — single source of truth.
# search/filters.py and Cartograph._normalize_language both use this.
LANGUAGE_ALIASES = {
    "js": "javascript", "ecmascript": "javascript",
    "ts": "typescript",
    "py": "python", "python3": "python", "py3": "python",
    "rs": "rust",
    "golang": "go",
    "c++": "cpp", "cxx": "cpp",
    "c#": "csharp",
    "hipc++": "hip", "hip c++": "hip",
    "sv": "systemverilog", "verilog": "systemverilog",
    "ang": "angular", "ng": "angular",
}

def normalize_language(lang):
    """Normalize a language name/alias to its canonical form."""
    if not lang:
        return "unknown"
    lang = lang.lower().strip()
    return LANGUAGE_ALIASES.get(lang, lang.replace(" ", "").replace("-", ""))


def normalize_widget_id(widget_id: str) -> str:
    """Normalize a widget ID to its canonical (hyphenated) form.

    Users can type either hyphens or underscores - this always returns
    the canonical hyphenated form for library lookups. The filesystem
    path for Python widgets is handled separately by _python_dir_name().
    """
    if not widget_id:
        return widget_id
    return widget_id.replace("_", "-")


def python_dir_name(widget_id: str) -> str:
    """Return the filesystem directory name for a widget.

    Python and Nim widgets get underscores so the directory is importable
    (both languages cannot handle hyphens in import paths).
    Other languages keep the canonical hyphenated ID.
    """
    canonical = normalize_widget_id(widget_id)
    if canonical.endswith("-python") or canonical.endswith("-nim"):
        return canonical.replace("-", "_")
    return canonical


def widget_path(widget_id: str, project_root: str = None) -> str:
    """Return the absolute path to an installed widget's directory.

    Usage in consumer code:
        import sys
        from cartograph.engine import widget_path
        sys.path.insert(0, widget_path("infra-agent-cli-python"))
        from src.agent_cli import AgentCLI
    """
    if project_root is None:
        project_root = REPO_DIR
    return os.path.join(project_root, DEFAULT_INSTALL_DIR, python_dir_name(widget_id))


def _closest_language(query, available, max_distance=3):
    """Find the closest language match by edit distance. Returns None if nothing is close."""
    best, best_dist = None, max_distance + 1
    for lang in available:
        d = _edit_distance(query, lang)
        if d < best_dist:
            best, best_dist = lang, d
    return best if best_dist <= max_distance else None


def _edit_distance(a, b):
    """Levenshtein distance between two strings."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[len(b)]


class Cartograph:
    def __init__(self, library_path):
        self.library_path = library_path
        self.widgets = []
        self.install_stats = self._load_install_stats()
        self._load_library()

        from .search import HybridBackend
        self._search_backend = HybridBackend()
        self._search_backend.build(self.widgets)

    def reload(self):
        """Re-scan the library from disk and rebuild the search index."""
        self.widgets = []
        self._load_library()
        self._search_backend.build(self.widgets)


    def _calculate_implementation_hash(self, path):
        return calculate_implementation_hash(path)

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
            return {"rating": 0, "count": 0, "trend": None, "reviews": [], "version_averages": {}}
        
        try:
            with open(review_path, 'r') as f:
                data = json.load(f)
                reviews = data.get("reviews", [])
                if not reviews:
                    return {"rating": 0, "count": 0, "trend": None, "reviews": [], "version_averages": {}}
                
                total_score = sum(r.get("rating", 0) for r in reviews)
                avg_rating = round(total_score / len(reviews), 1)
                
                # Group by version to find regressions
                version_ratings = {}
                for r in reviews:
                    v = r.get("version", "unknown")
                    if v not in version_ratings: version_ratings[v] = []
                    version_ratings[v].append(r.get("rating", 0))
                
                v_averages = {v: sum(rs)/len(rs) for v, rs in version_ratings.items()}

                # Trend: compare latest version's average to lifetime
                # Need at least 2 versions with reviews to show a trend
                if len(v_averages) >= 2:
                    latest_v = sorted(v_averages.keys(), key=semver_key)[-1]
                    latest_avg = v_averages[latest_v]
                    if latest_avg > avg_rating + 0.3:
                        trend = "up"
                    elif latest_avg < avg_rating - 0.3:
                        trend = "down"
                    else:
                        trend = "stable"
                else:
                    trend = None  # not enough data

                return {
                    "rating": avg_rating,
                    "count": len(reviews),
                    "trend": trend,
                    "reviews": reviews,
                    "version_averages": v_averages
                }
        except (OSError, json.JSONDecodeError, KeyError):
            return {"rating": 0, "count": 0, "trend": None, "reviews": [], "version_averages": {}}

    # Minimum reviews before a widget's raw rating is fully trusted.
    _RATING_CONFIDENCE_THRESHOLD = 5

    def _compute_weighted_ratings(self):
        """Apply Bayesian averaging to widget ratings.

        weighted = (count * avg + C * M) / (count + C)

        C = confidence threshold (reviews needed to trust the raw rating)
        M = global mean rating across all rated widgets

        Widgets with few reviews regress toward the global mean;
        widgets with many reviews converge to their raw average.
        """
        C = self._RATING_CONFIDENCE_THRESHOLD
        rated = [w for w in self.widgets if w["review_count"] > 0]
        if not rated:
            for w in self.widgets:
                w["weighted_rating"] = 0
            return
        M = sum(w["rating"] for w in rated) / len(rated)
        for w in self.widgets:
            count = w["review_count"]
            avg = w["rating"]
            if count == 0:
                w["weighted_rating"] = 0
            else:
                w["weighted_rating"] = round((count * avg + C * M) / (count + C), 2)

    def _load_install_stats(self):
        """Load install counts from stats.json."""
        if not os.path.exists(INSTALL_STATS_PATH):
            return {}
        try:
            with open(INSTALL_STATS_PATH, 'r') as f:
                data = json.load(f)
                return data.get("installs", {})
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_install_stats(self):
        os.makedirs(CARTOGRAPH_DIR, exist_ok=True)
        temp_path = INSTALL_STATS_PATH + ".tmp"
        try:
            with open(temp_path, 'w') as f:
                json.dump({"installs": self.install_stats}, f, indent=2)
            os.replace(temp_path, INSTALL_STATS_PATH)
        except Exception as e:
            log.warning("Failed to save stats: %s", e)

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

    def _normalize_language(self, lang):
        return normalize_language(lang)

    def _load_library_cache(self):
        """Load the mtime-based library cache from disk."""
        if not os.path.exists(LIBRARY_CACHE_PATH):
            return {}
        try:
            with open(LIBRARY_CACHE_PATH, 'r') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_library_cache(self, cache):
        """Persist the library cache to disk (atomic write)."""
        os.makedirs(CARTOGRAPH_DIR, exist_ok=True)
        temp_path = LIBRARY_CACHE_PATH + ".tmp"
        try:
            with open(temp_path, 'w') as f:
                json.dump(cache, f)
            os.replace(temp_path, LIBRARY_CACHE_PATH)
        except OSError as e:
            log.warning("Failed to save library cache: %s", e)

    def _get_src_max_mtime(self, widget_path):
        """Get the max mtime of files in src/ using listdir + stat (cheap)."""
        src_path = os.path.join(widget_path, "src")
        if not os.path.exists(src_path):
            return 0.0
        max_mtime = 0.0
        try:
            for entry in os.listdir(src_path):
                fp = os.path.join(src_path, entry)
                if os.path.isfile(fp):
                    mt = os.path.getmtime(fp)
                    if mt > max_mtime:
                        max_mtime = mt
        except OSError:
            pass
        return max_mtime

    def _load_library(self):
        """Scans the library, handles legacy schemas, and infers domains."""
        if not os.path.exists(self.library_path):
            log.warning("Library path not found: %s", self.library_path)
            return

        cache = self._load_library_cache()
        cache_dirty = False

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

                # Check cache: compare mtimes to decide if we can skip expensive ops
                manifest_mtime = os.path.getmtime(manifest_path)
                src_max_mtime = self._get_src_max_mtime(widget_path)
                review_path = os.path.join(widget_path, "reviews.json")
                reviews_mtime = os.path.getmtime(review_path) if os.path.exists(review_path) else 0.0

                cached = cache.get(item_id)
                cache_hit = (
                    cached is not None
                    and cached.get("manifest_mtime") == manifest_mtime
                    and cached.get("src_max_mtime") == src_max_mtime
                    and cached.get("reviews_mtime") == reviews_mtime
                )

                if cache_hit:
                    implementation_hash = cached["implementation_hash"]
                    test_count = cached["test_count"]
                    total_lines = cached["lines_of_code"]
                    review_data = {
                        "rating": cached["rating"],
                        "count": cached["review_count"],
                        "trend": cached.get("trend"),
                        "reviews": cached.get("reviews", []),
                        "version_averages": cached.get("version_averages", {}),
                    }
                else:
                    # Compute stats (expensive)
                    test_count = self._count_tests(widget_path)
                    review_data = self._load_reviews(widget_path)
                    implementation_hash = self._calculate_implementation_hash(widget_path)

                    total_lines = 0
                    src_dir = os.path.join(widget_path, "src")
                    if os.path.exists(src_dir):
                        for src_file in glob.glob(os.path.join(src_dir, "*.*")):
                            try:
                                total_lines += len(open(src_file).read().splitlines())
                            except (OSError, UnicodeDecodeError):
                                pass

                    cache[item_id] = {
                        "manifest_mtime": manifest_mtime,
                        "src_max_mtime": src_max_mtime,
                        "reviews_mtime": reviews_mtime,
                        "implementation_hash": implementation_hash,
                        "test_count": test_count,
                        "lines_of_code": total_lines,
                        "rating": review_data["rating"],
                        "review_count": review_data["count"],
                        "trend": review_data.get("trend"),
                        "reviews": review_data["reviews"],
                        "version_averages": review_data.get("version_averages", {}),
                    }
                    cache_dirty = True

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
                    "install_count": self._get_install_count(item_id),
                    "rating": review_data["rating"],
                    "review_count": review_data["count"],
                    "trend": review_data.get("trend"),
                    "reviews": review_data["reviews"],
                    "test_count": test_count,
                    "lines_of_code": total_lines,
                })
            except (OSError, json.JSONDecodeError, KeyError):
                continue

        if cache_dirty:
            self._save_library_cache(cache)

        # Bayesian weighted ratings - regress toward global mean until enough
        # reviews accumulate. Prevents a single 5-star review from dominating.
        self._compute_weighted_ratings()

        # Filter out widgets for unavailable languages if configured
        from .config import load_config
        if not load_config().get("library", {}).get("show_unavailable", True):
            from .languages import available_languages
            allowed = available_languages()
            self.widgets = [w for w in self.widgets
                           if normalize_language(w.get("language", "")) in allowed]

    def list_popular(self, limit=10):
        from .inspector import list_popular
        return list_popular(self, limit)
    def inspect(self, widget_id, show_source=False, show_all_versions=False,
                show_reviews=False, version=None):
        from .inspector import inspect
        widget_id = normalize_widget_id(widget_id)
        return inspect(self, widget_id, show_source=show_source,
                       show_all_versions=show_all_versions,
                       show_reviews=show_reviews, version=version)
    def create(self, item_id, language=None, name=None, domain="backend", tags=None,
                target_dir=None, gpu_targets=None, widget_type=None):
        from .scaffolding import create_widget
        item_id = normalize_widget_id(item_id)
        return create_widget(self, item_id, language=language, name=name, domain=domain,
                             tags=tags, target_dir=target_dir, gpu_targets=gpu_targets,
                             widget_type=widget_type)

    def search(self, query, domain_filter=None, language_filter=None, top_k=10):
        """Search the widget library using hybrid TF-IDF + n-gram fuzzy matching."""
        if language_filter:
            normalized = normalize_language(language_filter)
            available = {normalize_language(w.get("language", "")) for w in self.widgets}
            available.discard("unknown")
            if normalized not in available:
                suggestion = _closest_language(normalized, available)
                msg = f"No widgets in '{language_filter}'."
                if suggestion:
                    msg += f" Did you mean '{suggestion}'?"
                else:
                    msg += f" Available: {', '.join(sorted(available))}"
                return {"results": [], "message": msg}

        return self._search_backend.query(
            query,
            domain_filter=domain_filter,
            language_filter=language_filter,
            top_k=top_k,
        )

    def validate_item(self, path):
        from .validator import validate_item
        return validate_item(self, path)
    def checkin(self, path, reason="", version_bump="minor",
                override_warnings=False, override_reason=""):
        from .checkin import checkin
        return checkin(self, path, reason=reason, version_bump=version_bump,
                       override_warnings=override_warnings, override_reason=override_reason)
    def restore(self, item_id, version, reason):
        from .checkin import restore
        return restore(self, item_id, version, reason)
    def add_review(self, widget_id, target_dir, score, comment=None):
        from .checkin import add_review
        widget_id = normalize_widget_id(widget_id)
        return add_review(self, widget_id, target_dir, score, comment=comment)
    def widget_status(self, widget_id, target_dir):
        from .checkin import widget_status
        widget_id = normalize_widget_id(widget_id)
        return widget_status(self, widget_id, target_dir)
    def install(self, widget_id, target_dir, version=None):
        from .installer import install
        widget_id = normalize_widget_id(widget_id)
        return install(self, widget_id, target_dir, version=version)
    def uninstall(self, widget_id, target_dir):
        from .installer import uninstall
        widget_id = normalize_widget_id(widget_id)
        return uninstall(self, widget_id, target_dir)
    def upgrade(self, widget_id, target_dir, version=None):
        from .installer import upgrade
        widget_id = normalize_widget_id(widget_id)
        return upgrade(self, widget_id, target_dir, version=version)
    def delete(self, widget_id, confirm=False):
        from .installer import delete_from_library
        widget_id = normalize_widget_id(widget_id)
        return delete_from_library(self, widget_id, confirm=confirm)
