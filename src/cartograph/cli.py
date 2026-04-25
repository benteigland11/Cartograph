"""
Cartograph CLI — manage your widget library from the terminal.

Every command that takes a path defaults to the current directory (.).
Output is always JSON so both humans and AI agents can consume it.
"""

import json
import os
import shutil
import sys
import urllib.parse
import zipfile
from io import BytesIO

try:
    from cg.infra_agent_cli_python.src.agent_cli import AgentCLI, out, err
except ModuleNotFoundError as _e:
    # Most common cause: another installed package (or the user's own
    # project cwd) contains a top-level cg/__init__.py. That turns cg/
    # into a regular package and shadows cartograph's bundled widgets.
    # Surface the real cause instead of a stdlib-flavored traceback.
    if _e.name and _e.name.startswith("cg"):
        import json as _json
        import sys as _sys
        import cg as _cg_mod  # type: ignore
        cg_paths = list(getattr(_cg_mod, "__path__", []) or [])
        shadowers = [
            os.path.join(p, "__init__.py")
            for p in cg_paths
            if os.path.isfile(os.path.join(p, "__init__.py"))
        ]
        msg = (
            "cartograph cannot find its bundled widgets under the cg/ "
            "namespace. This almost always means a cg/__init__.py file "
            "is present on the Python path and has turned cg/ into a "
            "regular package, shadowing every other contributor."
        )
        payload = {
            "status": "error",
            "error": msg,
            "cg_paths": cg_paths,
            "offending_init_files": shadowers,
            "fix": "Remove any cg/__init__.py in your project or in an "
                   "installed package. cg/ must remain a PEP 420 namespace "
                   "package.",
        }
        print(_json.dumps(payload, indent=2))
        _sys.exit(1)
    raise


def _check_and_prompt_tos():
    """Check TOS status and prompt user to accept if needed."""
    from .cloud import check_tos, get_tos, accept_tos
    status = check_tos()
    if "error" in status or status.get("accepted", True):
        return

    # Need to accept TOS
    tos = get_tos()
    if "error" in tos:
        print("  Warning: Could not fetch Terms of Service.")
        return

    print(f"\n{'='*60}")
    print(tos.get("text", ""))
    print(f"{'='*60}\n")

    if not sys.stdin.isatty():
        print("  TOS acceptance required. Run `cartograph login` interactively.")
        return

    answer = input("  Do you accept the Terms of Service? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        result = accept_tos()
        if "error" in result:
            print(f"  Warning: Could not record TOS acceptance: {result['error']}")
        else:
            print(f"  Terms of Service v{tos.get('version', '?')} accepted.")
    else:
        print("  TOS not accepted. You will not be able to publish widgets.")


def _resolve_widget(path: str) -> str:
    """Resolve a widget directory.

    Accepts a full path, a relative path, or just a widget_id.
    If the path doesn't exist or lacks widget.json, tries cg/<path>/
    from the current directory.
    """
    resolved = os.path.abspath(path)
    if os.path.isfile(os.path.join(resolved, "widget.json")):
        return resolved

    # Try cg/<path>/ from cwd (handles bare widget_id like "logic-test-python")
    # Skip if path already starts with cg/ to avoid doubling
    from .engine import DEFAULT_INSTALL_DIR
    if not path.startswith(DEFAULT_INSTALL_DIR + os.sep) and not path.startswith(DEFAULT_INSTALL_DIR + "/"):
        candidate = os.path.join(os.getcwd(), DEFAULT_INSTALL_DIR, path)
        if os.path.isfile(os.path.join(candidate, "widget.json")):
            return os.path.abspath(candidate)

    return resolved


def _carto():
    from .engine import Cartograph, LIBRARY_PATH
    return Cartograph(LIBRARY_PATH)


def _preflight_language(language: str) -> None:
    """Exit with a clear message if the language engine's system deps aren't met."""
    from .languages import get_engine
    engine = get_engine(language)
    if engine is None:
        return
    ok, msg = engine.check_available()
    if not ok:
        print(f"\n  ✗ {msg}\n", file=sys.stderr)
        sys.exit(1)


def _preflight_from_path(path: str) -> None:
    """Read widget.json language and run preflight check."""
    manifest = os.path.join(path, "widget.json")
    if not os.path.isfile(manifest):
        return  # command itself will report the missing file
    try:
        with open(manifest) as f:
            language = json.load(f).get("tech_stack", {}).get("language", "python")
        _preflight_language(language)
    except json.JSONDecodeError:
        print(f"\n  Warning: widget.json is malformed at {path}\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Registry widget ID parsing
# ---------------------------------------------------------------------------

def _parse_registry_id(widget_id):
    """Parse @owner/prefix-widget-name into (owner, registry_url, bare_id).

    Returns (owner, registry_url, bare_id) on success, or raises SystemExit
    with an error if the format is invalid. registry_url is None for the
    public registry (callers pass None to cloud functions to use the default).
    """
    from .config import get_registries, _PUBLIC_REGISTRY_PREFIX, _PUBLIC_REGISTRY_URL

    if not widget_id.startswith("@"):
        return None

    parts = widget_id[1:].split("/", 1)
    if len(parts) != 2:
        err({"error": f"Invalid format: '{widget_id}'. Use @owner/prefix-widget-name."})

    owner, prefixed_id = parts
    all_prefixes = [(_PUBLIC_REGISTRY_PREFIX, None)] + \
                   [(r["prefix"], r["url"]) for r in get_registries()]

    for prefix, url in all_prefixes:
        if prefixed_id.startswith(prefix + "-"):
            bare_id = prefixed_id[len(prefix) + 1:]
            return owner, url, bare_id

    # Unknown prefix - pass through as-is to public registry
    return owner, None, prefixed_id


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _search_registries(query, domain_filter, language_filter, top_k):
    """Search public registry + all configured company registries.

    Returns (all_widgets, errors) where each widget is annotated with
    'registry_prefix' so callers can construct the correct install command.
    """
    from .cloud import search as cloud_search
    from .config import get_registries, _PUBLIC_REGISTRY_PREFIX

    all_widgets = []
    errors = {}

    def _fetch(prefix, registry_url):
        result = cloud_search(query, domain_filter, language_filter,
                              top_k=top_k, registry_url=registry_url)
        if result.get("error"):
            errors[prefix] = result["error"]
        for w in result.get("widgets", []):
            # Rewrite id to unambiguous install form: @owner/prefix-widget-name
            wid = w.get("id", "")
            if "/" in wid:
                owner_part, base = wid.split("/", 1)  # "@owner", "widget-name"
            else:
                owner_part, base = "", wid
            w["id"] = f"{owner_part}/{prefix}-{base}" if owner_part else f"{prefix}-{base}"
            w["registry_prefix"] = prefix
        return result.get("widgets", [])

    # Public registry (None = default URL)
    all_widgets.extend(_fetch(_PUBLIC_REGISTRY_PREFIX, None))

    # Company registries
    for reg in get_registries():
        all_widgets.extend(_fetch(reg["prefix"], reg["url"]))

    return all_widgets, errors


def cmd_search(args):
    local = _carto().search(
        query=args.query,
        domain_filter=args.domain,
        language_filter=args.language,
        top_k=args.top_k,
    )

    # Search all registries if cloud is enabled
    from .config import cloud_enabled
    if cloud_enabled():
        registry_widgets, registry_errors = _search_registries(
            args.query, args.domain, args.language, args.top_k
        )
    else:
        registry_widgets, registry_errors = [], {}

    # Cloud results have id="@owner/cg-widget-name", local have id="widget-name".
    # Strip both @owner/ and any registry prefix to get a bare comparable id.
    from .config import get_registries, _PUBLIC_REGISTRY_PREFIX
    _all_prefixes = [_PUBLIC_REGISTRY_PREFIX] + [r["prefix"] for r in get_registries()]

    def _base_id(w):
        wid = w.get("id", "")
        base = wid.split("/", 1)[1] if "/" in wid else wid
        for pfx in _all_prefixes:
            if base.startswith(pfx + "-"):
                return base[len(pfx) + 1:]
        return base

    local_widgets = local.get("results", [])

    # Dedup registry results: same (registry_prefix, base_id) → highest relevance wins.
    # Same base_id across DIFFERENT registries stays separate (different install targets).
    seen_registry = {}
    for w in registry_widgets:
        key = (w.get("registry_prefix", ""), _base_id(w))
        existing = seen_registry.get(key)
        if existing is None or w.get("relevance_score", 0) > existing.get("relevance_score", 0):
            seen_registry[key] = w

    # Only suppress a local widget if the cloud version belongs to the current user.
    # Someone else's same-named widget in a registry should not hide your local copy.
    # Short-circuit if not authenticated to avoid a network call on every search.
    _me = ""
    try:
        from .auth import is_authenticated
        from .cloud import whoami as _whoami
        if is_authenticated():
            _profile = _whoami()
            _me = _profile.get("owner", "") or _profile.get("username", "")
    except Exception:
        pass

    registry_base_ids = set()
    for w in seen_registry.values():
        wid = w.get("id", "")
        if "/" in wid:
            owner = wid.split("/", 1)[0].lstrip("@")
            if _me and owner == _me:
                registry_base_ids.add(_base_id(w))
        # no owner info or not your widget → don't suppress local

    # Local: keep only widgets not present in any registry
    seen_local = {}
    for w in local_widgets:
        bid = _base_id(w)
        if bid not in registry_base_ids:
            seen_local[bid] = w

    local_sorted = sorted(seen_local.values(), key=lambda w: w.get("relevance_score", 0), reverse=True)
    # All registry results pooled and sorted by relevance
    registry_sorted = sorted(seen_registry.values(), key=lambda w: w.get("relevance_score", 0), reverse=True)

    # Local fills first; all registries combined share the remaining half.
    _REGISTRY_CAP = args.top_k // 2
    if local_sorted and registry_sorted:
        local_take = min(len(local_sorted), args.top_k)
        registry_take = min(len(registry_sorted), args.top_k - local_take, _REGISTRY_CAP)
    elif local_sorted:
        local_take = min(len(local_sorted), args.top_k)
        registry_take = 0
    else:
        local_take = 0
        registry_take = min(len(registry_sorted), args.top_k)

    combined = local_sorted[:local_take] + registry_sorted[:registry_take]

    merged = {
        "local_count": local_take,
        "registry_count": registry_take,
        "widgets": combined,
    }
    if registry_errors:
        merged["registry_errors"] = registry_errors

    if not combined:
        out({
            "local_count": 0,
            "registry_count": 0,
            "widgets": [],
            "message": f"No widgets found for \'{args.query}\'.",
            "suggestion": "Try broadening your search by removing --domain or --language filters." if args.domain or args.language else "Run \'cartograph doctor\' to check available language engines."
        })
        return

    out(merged)


def cmd_inspect(args):
    widget_id = args.widget_id

    # Cloud widget: @owner/prefix-widget-name
    if widget_id.startswith("@"):
        parsed = _parse_registry_id(widget_id)
        owner, registry_url, bare_id = parsed
        from .cloud import inspect as cloud_inspect
        result = cloud_inspect(owner, bare_id, source=args.source, registry_url=registry_url)
        if "error" in result:
            err(result)
        out(result)
        return

    result = _carto().inspect(
        widget_id=widget_id,
        show_source=args.source,
        show_all_versions=args.all_versions,
        show_reviews=args.reviews,
        version=getattr(args, "version", None),
    )
    out(result)


def _cloud_install_note(result):
    """Print a trust note if the widget came from a registry that doesn't validate."""
    if result.get("source") != "cloud":
        return
    from .cloud import registry_info
    info = registry_info()
    if not info.get("validates", False):
        print("    Note: Code is validated locally by the uploader. Review before use.", file=sys.stderr)


def cmd_install(args):
    result = _carto().install(
        widget_id=args.widget_id,
        target_dir=os.path.abspath(args.target),
        version=args.version,
    )
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)
    _cloud_install_note(result)


def _resolve_installed_widget(widget_dir: str, default_target: str):
    """Resolve a widget directory into (widget_id, target_dir, dir_name).

    Accepts either:
    - A path (relative or absolute) to an installed widget dir
      (e.g. cg/infra_file_stamp_python), or
    - A bare directory basename (e.g. cg_backend_xai_client_python),
      which is auto-resolved under <default_target>/cg/.

    widget_id is the prefixed form when the dir name carries a registry
    prefix (e.g. cg_foo -> cg-foo), so callers that refetch (upgrade) hit
    the right registry. dir_name is the actual directory basename, so
    rmtree-style operations target the correct path.

    Project root is derived as the parent-of-parent of the resolved dir.
    """
    from .engine import DEFAULT_INSTALL_DIR, python_dir_name

    candidate = os.path.abspath(widget_dir)
    if not os.path.isdir(candidate):
        # Try as a bare basename under <default_target>/cg/
        fallback = os.path.abspath(
            os.path.join(default_target, DEFAULT_INSTALL_DIR, widget_dir)
        )
        if os.path.isdir(fallback):
            candidate = fallback
        else:
            err({"error": (
                f"'{widget_dir}' not found. Pass the installed widget directory "
                f"(e.g. cg/infra_file_stamp_python) or its basename. "
                f"Run 'cartograph status --all' to see installed widget paths."
            )})
    manifest = os.path.join(candidate, "widget.json")
    try:
        with open(manifest) as f:
            canonical_id = json.load(f).get("meta", {}).get("id", "")
        if not canonical_id:
            err({"error": f"widget.json at {manifest} is missing meta.id"})
    except Exception as e:
        err({"error": f"Could not read widget.json at {manifest}: {e}"})

    dir_name = os.path.basename(candidate)
    target_dir = os.path.dirname(os.path.dirname(candidate))

    # If the dir basename carries a registry prefix (cg-foo, myorg-foo),
    # reconstruct the prefixed widget_id so refetch lands in the right
    # registry. Otherwise the canonical meta.id is correct.
    canonical_dir = python_dir_name(canonical_id)
    widget_id = canonical_id
    if dir_name != canonical_dir and dir_name.endswith(canonical_dir):
        sep_len = len(dir_name) - len(canonical_dir)
        prefix = dir_name[:sep_len].rstrip("_-")
        if prefix:
            widget_id = f"{prefix}-{canonical_id}"
    return widget_id, target_dir, dir_name


def cmd_uninstall(args):
    widget_id, target_dir, _ = _resolve_installed_widget(args.widget_dir, os.getcwd())
    result = _carto().uninstall(widget_id=widget_id, target_dir=target_dir)
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)


def cmd_upgrade(args):
    widget_id, target_dir, _ = _resolve_installed_widget(args.widget_dir, os.getcwd())
    result = _carto().upgrade(
        widget_id=widget_id,
        target_dir=target_dir,
        version=args.version,
    )
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)
    _cloud_install_note(result)


def cmd_delete(args):
    result = _carto().delete(
        widget_id=args.widget_id,
        confirm=args.confirm,
    )
    if result.get("status") == "error" or "error" in result:
        err(result)

    # Also remove from cloud if published
    if result.get("status") == "success":
        from . import cloud, auth
        if auth.is_authenticated() and cloud.is_available():
            cloud_result = cloud.delete_widget(args.widget_id)
            if "error" not in cloud_result:
                result["cloud"] = "deleted"
            # Silently skip if not on cloud (404)

    out(result)


def cmd_create(args):
    _preflight_language(args.language)
    target_abs = os.path.abspath(args.target)
    # Block creating directly inside the library. Widgets must be built in a
    # project dir and checked in via `cartograph checkin` so they go through
    # validation and version management. Creating in the library bypasses both.
    from .engine import LIBRARY_PATH
    lib_abs = os.path.abspath(LIBRARY_PATH)
    try:
        in_library = os.path.commonpath([target_abs, lib_abs]) == lib_abs
    except ValueError:
        in_library = False
    if in_library:
        err({"error": (
            f"Refusing to create a widget inside the library at {lib_abs}. "
            f"Run the command from your project root without --target (defaults to .); "
            f"then `cartograph checkin` publishes it to the library."
        )})
    result = _carto().create(
        item_id=args.widget_id,
        language=args.language,
        domain=args.domain,
        name=args.name,
        target_dir=target_abs,
    )
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)


def cmd_rename(args):
    result = _carto().rename_widget(
        old_id=args.widget_id,
        new_name=args.name,
        new_domain=args.domain,
        target_dir=os.path.abspath(args.target),
    )
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)


def _resolve_widget_path(args) -> str:
    """Resolve a widget path from either --lib <widget_id> or a filesystem path."""
    if getattr(args, "lib", False):
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == args.path), None)
        if not widget:
            err({"error": f"Widget '{args.path}' not found in library. Use 'cartograph search' to browse."})
        return widget["path"]
    return _resolve_widget(args.path)


def _check_cg_namespace_hygiene(root: str) -> str | None:
    """Return an error message if <root>/cg/__init__.py exists, else None.

    A top-level cg/__init__.py turns the cg/ namespace into a regular
    package. If this project is later installed or packaged, that file
    shadows every other contributor to the cg/ namespace on the user's
    system — silently breaking Cartograph (and any other package that
    ships widgets under cg/). Agents often scaffold __init__.py out of
    habit, so we catch it before it propagates.
    """
    bad = os.path.join(root, "cg", "__init__.py")
    if os.path.isfile(bad):
        return (
            f"cg/__init__.py detected at {bad}. "
            "Remove it — the cg/ directory must stay a namespace package "
            "(PEP 420). Shipping this file breaks Cartograph on every "
            "machine this project installs to."
        )
    return None


def cmd_validate(args):
    path = _resolve_widget_path(args)
    _preflight_from_path(path)
    # Project-level hygiene check — the user's cwd is where a toxic
    # cg/__init__.py would live. Hard block because validate is the gate
    # before checkin/publish, and the cost of this file shipping into
    # anyone else's environment is much worse than making the user
    # delete a one-line file.
    hygiene_error = _check_cg_namespace_hygiene(os.getcwd())
    if hygiene_error:
        err({"status": "error", "error": hygiene_error})
    result = _carto().validate_item(path=path)
    if result.get("status") == "error" or "error" in result:
        err(result)
    if result.get("warnings"):
        print("\nWarnings:", file=sys.stderr)
        for w in result["warnings"]:
            print(f"  {w}", file=sys.stderr)
        print("", file=sys.stderr)
    out(result)


def _read_source_meta(install_path: str) -> dict | None:
    """Read .cartograph_source sidecar if present. Returns {owner, registry_url} or None."""
    sidecar = os.path.join(install_path, ".cartograph_source")
    if not os.path.isfile(sidecar):
        return None
    try:
        with open(sidecar) as f:
            return json.load(f)
    except Exception:
        return None


def _config_publish_registry_url() -> str | None:
    """Return the registry URL from the publish-registry config key, or None for public default."""
    from .config import get_value, get_registry_url_for_prefix
    configured_prefix, _ = get_value("publish-registry")
    if configured_prefix:
        return get_registry_url_for_prefix(configured_prefix)
    return None


def _force_push(checkin_result: dict, install_path: str | None = None,
                reason: str = "") -> None:
    """Push to cloud, or propose to origin owner if widget was installed from someone else.

    Registry resolution order:
      1. Sidecar at install_path (previously established home for own widgets,
         or origin registry for proposal routing)
      2. publish-registry config key
      3. Public registry (default)
    """
    from . import cloud, auth
    from .config import load_config
    if not auth.is_authenticated():
        print("  → Cannot push: not authenticated. Run: cartograph login", file=sys.stderr)
        return
    widget_id = checkin_result.get("id", "")
    widget_path = checkin_result.get("path", "")
    if not widget_id or not widget_path:
        return

    # Check sidecar: if installed from another owner, route as a proposal
    source = _read_source_meta(install_path) if install_path else None
    if source:
        origin_owner = source.get("owner", "")
        current_user = cloud.whoami().get("owner", "")
        if origin_owner and current_user and origin_owner != current_user:
            origin_registry = source.get("registry_url")
            print(f"  → Widget installed from @{origin_owner} - submitting as proposal...", file=sys.stderr)
            propose_result = cloud.propose(widget_path, origin_owner, widget_id,
                                           reason=reason or "Improvement proposal",
                                           registry_url=origin_registry)
            if propose_result.get("error"):
                print(f"  → Proposal failed: {propose_result['error']}", file=sys.stderr)
            else:
                status = propose_result.get("status", "proposed")
                print(f"  → Proposal {status}: {propose_result.get('proposal_id', '')}", file=sys.stderr)
                # Governance is inferred from the route the server took:
                # "published" == origin was open (auto-merged)
                # "proposed"  == origin was protected (queued for review)
                inferred = "open (auto-merged)" if status == "published" else "protected (queued for review)"
                print(f"  → governance: {inferred}  |  origin: @{origin_owner}", file=sys.stderr)
            return
        # Own widget - sidecar has previously established home registry
        registry_url = source.get("registry_url")
    else:
        # No sidecar - fall back to publish-registry config
        registry_url = _config_publish_registry_url()
    cfg = load_config()
    visibility = cfg["publish"]["visibility"]
    governance = cfg["publish"].get("governance")
    print(f"  → Pushing {widget_id} v{checkin_result.get('version', '?')} to cloud...", file=sys.stderr)
    push_result = cloud.push(widget_path, widget_id, visibility=visibility,
                             governance=governance, registry_url=registry_url)
    if push_result.get("error"):
        print(f"  → Push failed: {push_result['error']}", file=sys.stderr)
    else:
        from .config import get_registry_url_for_prefix, get_registries, _PUBLIC_REGISTRY_PREFIX
        namespaced = push_result.get("namespaced_id", "")
        version = push_result.get("version", "?")
        # Reconstruct full install command: @owner/prefix-widget-name
        if "/" in namespaced:
            owner_part, bare = namespaced.split("/", 1)
            prefix = _PUBLIC_REGISTRY_PREFIX
            for reg in get_registries():
                if (reg["url"] or "").rstrip("/") == (registry_url or "").rstrip("/"):
                    prefix = reg["prefix"]
                    break
            install_id = f"{owner_part}/{prefix}-{bare}"
        else:
            install_id = namespaced
        print(f"  → Published v{version}  |  install: cartograph install {install_id}", file=sys.stderr)
        # Write sidecar: records home registry, owner, and governance as declared at publish time
        try:
            from .config import _PUBLIC_REGISTRY_URL
            current_user = cloud.whoami().get("owner", "")
            sidecar = {
                "owner": current_user,
                "registry_url": registry_url or _PUBLIC_REGISTRY_URL,
            }
            published_governance = push_result.get("governance")
            if published_governance:
                sidecar["governance"] = published_governance
            with open(os.path.join(widget_path, ".cartograph_source"), "w") as _f:
                json.dump(sidecar, _f)
            # One-line governance reminder on every cloud write. Keeps the
            # author aware of which model their widget ships under without
            # nagging (no actionable "change it with" text — cloud settings
            # is in the command reference for when someone actually wants to
            # flip it).
            # Owner comes from the server response (namespaced_id = owner/id)
            # — the registry is the authority on which account the widget
            # actually landed under. No whoami fallback (that conflates "who
            # am I" with "who owns this widget").
            effective_gov = published_governance or governance or "protected"
            owner_handle = namespaced.split("/", 1)[0] if "/" in namespaced else ""
            # namespaced_id from the server already carries the @ prefix
            owner_tag = owner_handle if owner_handle.startswith("@") else (f"@{owner_handle}" if owner_handle else "unknown")
            print(f"  → governance: {effective_gov}  |  owner: {owner_tag}", file=sys.stderr)
        except Exception:
            pass  # sidecar is best-effort; push already succeeded


def cmd_checkin(args):
    install_path = _resolve_widget(args.path)
    _preflight_from_path(install_path)
    result = _carto().checkin(
        path=install_path,
        reason=args.reason,
        version_bump=args.bump,
        override_warnings=args.override_warnings,
        override_reason=args.override_reason or "",
    )
    if result.get("status") == "error" or "error" in result:
        err(result)
    out(result)

    # Push to cloud only when the user opts in: --publish flag or auto_publish=True.
    # The old "else: auto-push if already published" branch was removed — it
    # silently pushed on every checkin of a cloud-originated widget regardless
    # of the user's auto_publish setting, which contradicts auto_publish=False.
    if result.get("action") in ("updated", "registered"):
        from .config import load_config
        cfg = load_config()
        publish = getattr(args, "publish", False) or cfg["publish"]["auto_publish"]
        if publish:
            _force_push(result, install_path=install_path, reason=args.reason)


_PAGINATE_FN = None


def _paginate_widget():
    """Dogfooded universal-list-paginator-python widget, loaded by file path to
    avoid the `src/` package-name collision with this repo's own `src/cartograph/`.
    Lazily loaded so cli.py startup stays cheap and doesn't fail if cg/ is pruned.
    """
    global _PAGINATE_FN
    if _PAGINATE_FN is not None:
        return _PAGINATE_FN
    import importlib.util
    widget_file = _dogfood_widget_file("universal_list_paginator_python", "list_paginator.py")
    spec = importlib.util.spec_from_file_location("_cg_list_paginator", widget_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PAGINATE_FN = module.paginate
    return _PAGINATE_FN


def cmd_status(args):
    target = os.getcwd()
    # Soft check — surface as a warning on the response so agents/users
    # see it whether they run status on one widget or the full listing.
    # Validate is the hard gate; status is the early heads-up.
    hygiene_warning = _check_cg_namespace_hygiene(target)

    def _out(payload: dict) -> None:
        if hygiene_warning:
            payload.setdefault("warnings", []).append(hygiene_warning)
        out(payload)

    if args.widget_dir:
        # Pagination flags are meaningless for a single-target lookup — flag it
        # rather than silently ignoring, so an agent knows its call was ambiguous.
        if args.all_widgets or args.page != 1 or args.size != 20:
            err({"status": "error",
                 "message": "--page/--size/--all only apply when listing all widgets (omit widget_dir)."})
        widget_id, target, _ = _resolve_installed_widget(args.widget_dir, target)
        result = _carto().widget_status(widget_id=widget_id, target_dir=target)
        if result.get("error"):
            err(result)
        _out(result)
        return

    # No widget_id — scan all installed widgets
    from .engine import DEFAULT_INSTALL_DIR
    install_dir = os.path.join(target, DEFAULT_INSTALL_DIR)
    if not os.path.isdir(install_dir):
        _out({
            "status": "success",
            "widgets": [],
            "message": f"No widgets installed at {target}.",
            "suggestion": "Run \'cartograph install <widget_id>\' to install one."
        })
        return

    widget_ids = [
        d for d in os.listdir(install_dir)
        if os.path.isfile(os.path.join(install_dir, d, "widget.json"))
    ]

    if not widget_ids:
        _out({
            "status": "success",
            "widgets": [],
            "message": f"No widgets installed at {target}.",
            "suggestion": "Run \'cartograph install <widget_id>\' to install one."
        })
        return

    from .engine import normalize_widget_id, python_dir_name, DEFAULT_INSTALL_DIR
    from concurrent.futures import ThreadPoolExecutor, as_completed
    carto = _carto()
    library_by_id = {w["id"]: w for w in carto.widgets}

    def _has_sidecar(wid):
        """True if this widget has a cloud sidecar in its installed dir or library dir."""
        canonical = normalize_widget_id(wid)
        installed = os.path.join(install_dir, wid, ".cartograph_source")
        if os.path.isfile(installed):
            return True
        # Strip registry prefix to find library entry
        from .installer import _resolve_registry
        resolved = _resolve_registry(canonical)
        lib_id = resolved[2] if resolved else canonical
        lib_widget = library_by_id.get(lib_id)
        if lib_widget:
            lib_sidecar = os.path.join(lib_widget["path"], ".cartograph_source")
            return os.path.isfile(lib_sidecar)
        return False

    cloud_wids = [wid for wid in sorted(widget_ids) if _has_sidecar(wid)]
    local_wids = [wid for wid in sorted(widget_ids) if wid not in cloud_wids]

    results = {}
    for wid in local_wids:
        results[wid] = carto.widget_status(widget_id=normalize_widget_id(wid),
                                           target_dir=target, check_cloud=False)

    if cloud_wids:
        def _status_cloud(wid):
            return carto.widget_status(widget_id=normalize_widget_id(wid), target_dir=target)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_status_cloud, wid): wid for wid in cloud_wids}
            for fut in as_completed(futures):
                wid = futures[fut]
                try:
                    results[wid] = fut.result()
                except Exception as e:
                    results[wid] = {"error": str(e)}

    all_widgets = []
    for wid in sorted(widget_ids):
        r = results[wid]
        if "error" not in r:
            all_widgets.append(r)

    total = len(all_widgets)
    aggregate = {
        "installed": total,
        "outdated": sum(1 for w in all_widgets if w.get("outdated")),
        "modified": sum(1 for w in all_widgets if w.get("modified")),
    }

    def _has_issue(w):
        return w.get("outdated") or w.get("modified") or w.get("outdated_vs_cloud")

    from .engine import python_dir_name

    def _ver(s):
        try:
            return tuple(int(x) for x in str(s).split("."))
        except Exception:
            return (0,)

    def _suggest(w):
        wid = w["widget_id"]
        outdated = w.get("outdated", False)
        modified = w.get("modified", False)
        outdated_vs_cloud = w.get("outdated_vs_cloud", False)
        widget_dir = os.path.join(target, DEFAULT_INSTALL_DIR, python_dir_name(wid))

        installed_v = _ver(w.get("installed_version", "0"))
        library_v = _ver(w.get("library_version", "0"))
        cloud_v = _ver(w.get("cloud_version", "0")) if w.get("cloud_version") else None

        # Installed is ahead of library but matches cloud — local library is stale.
        if outdated and cloud_v and cloud_v == installed_v and installed_v > library_v:
            return "Local library is behind cloud. Run: cartograph cloud sync"

        # Cloud has a newer version than what's installed.
        if outdated_vs_cloud:
            return (f"Cloud registry has a newer version. Run: "
                    f"cartograph cloud sync && cartograph upgrade {widget_dir}")

        # Installed is behind library AND has local changes — need to inspect and merge.
        if outdated and modified and installed_v < library_v:
            return (f"Local changes conflict with a newer library version. "
                    f"Inspect what changed: "
                    f"cartograph inspect {wid} --source --version {w['library_version']} "
                    f"then upgrade and re-apply your changes: "
                    f"cartograph upgrade {widget_dir}")

        # Installed is simply behind the library.
        if outdated and installed_v < library_v:
            return f"cartograph upgrade {widget_dir}"

        # Local modifications only — suggest checkin if intentional.
        if modified:
            return (f"Local modifications detected. Check in if intentional: "
                    f"cartograph checkin {widget_dir} --reason \"...\"")
        return None

    for w in all_widgets:
        suggestion = _suggest(w)
        if suggestion:
            w["suggestion"] = suggestion

    if args.all_widgets:
        # --all: show every widget regardless of status, no pagination
        pagination = {
            "page": 1, "size": total, "total": total,
            "total_pages": 1, "has_next": False, "has_prev": False,
            "all": True,
        }
        page_items = all_widgets
    else:
        # Default: only surface widgets with issues
        problem_widgets = [w for w in all_widgets if _has_issue(w)]
        paginate = _paginate_widget()
        result = paginate(problem_widgets, page=args.page, size=args.size)
        page_items = result.pop("items")
        pagination = {**result, "all": False}
        # Agent-friendly: tell the caller exactly how to get the next/prev page.
        if pagination["has_next"]:
            pagination["next_command"] = (
                f"cartograph status --page {pagination['page'] + 1} --size {pagination['size']}"
            )
        if pagination["has_prev"]:
            pagination["prev_command"] = (
                f"cartograph status --page {pagination['page'] - 1} --size {pagination['size']}"
            )

    payload = {**aggregate, "pagination": pagination, "widgets": page_items}
    if not args.all_widgets:
        payload["note"] = (
            "Showing widgets with issues only. Run with --all to see all installed widgets."
            if aggregate["outdated"] or aggregate["modified"] else
            "All widgets are up to date."
        )
    _out(payload)


def cmd_login(args):
    token = args.token
    registry_prefix = getattr(args, "registry", None)

    if registry_prefix:
        # Company registry login: store API token keyed by registry URL
        if not token:
            err({"error": f"--token required for registry login. Use: cartograph login --token <key> --registry {registry_prefix}"})
        from .config import get_registry_url_for_prefix
        registry_url = get_registry_url_for_prefix(registry_prefix)
        if not registry_url:
            err({"error": f"Registry '{registry_prefix}' not configured. Add it first: cartograph registry add <url>"})
        from .auth import store_registry_token
        store_registry_token(registry_url, token)
        print(f"\n  Stored token for registry '{registry_prefix}' ({registry_url})\n")
        return

    if token:
        # Manual token login (legacy compat - treat as id_token with no refresh)
        from .cloud import login_with_credentials
        result = login_with_credentials(token, "", "")
        if "error" in result:
            err(result)

        from .config import list_values
        items = list_values()
        max_key = max((len(i["key"]) for i in items), default=0)
        max_val = max((len(str(i["value"] if i["value"] is not None else "-")) for i in items), default=0)
        print("\n  Your current settings:")
        for item in items:
            val = item["value"]
            display = str(val) if val is not None else "-"
            print(f"    {item['key']:<{max_key}}   {display:<{max_val}}   {item['description']}")
        print(f"\n  Run 'cartograph config <key> <value>' to change defaults.\n")

        out(result)
        return

    # No token given — use browser-based OAuth flow
    if not sys.stdin.isatty():
        err({"error": "Provide a token with --token or set CARTOGRAPH_TOKEN"})

    import http.server
    import webbrowser
    from .auth import get_registry_url, save_credentials

    received = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            def _first(key):
                val = params.get(key, "")
                if isinstance(val, list):
                    return val[0] if val else ""
                return val or ""
            id_token = _first("id_token")
            if id_token:
                received["id_token"] = id_token
                received["refresh_token"] = _first("refresh_token")
                received["signing_key"] = _first("signing_key")
                received["handle"] = _first("handle")
                received["client_id"] = _first("client_id")
                received["client_secret"] = _first("client_secret")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if id_token:
                self.wfile.write(
                    b"<html><body style='font-family:monospace;background:#0d1117;color:#e6edf3;"
                    b"max-width:500px;margin:60px auto;padding:20px'>"
                    b"<h2 style='color:#58a6ff'>Logged in</h2>"
                    b"<p>You can close this tab and return to your terminal.</p></body></html>"
                )
            else:
                self.wfile.write(b"")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    server.timeout = 120
    port = server.server_address[1]
    cli_redirect = f"http://127.0.0.1:{port}/callback"

    registry = get_registry_url().rstrip("/")
    login_url = f"{registry}/v1/auth/login?cli_redirect={urllib.parse.quote(cli_redirect)}"

    print(f"\n  Opening browser for authentication...")
    print(f"  If it doesn't open automatically, visit:\n  {login_url}\n")

    webbrowser.open(login_url)

    # Keep serving until we get credentials or timeout
    while "id_token" not in received:
        server.handle_request()
        if server.timeout and not received:
            break
    server.server_close()

    id_token = received.get("id_token", "")
    handle = received.get("handle", "")
    if not id_token:
        err({"error": "Authentication timed out or was cancelled."})

    save_credentials(
        id_token,
        received.get("refresh_token", ""),
        received.get("signing_key", ""),
        client_id=received.get("client_id", ""),
        client_secret=received.get("client_secret", ""),
    )
    print(f"  Logged in as @{handle}\n")

    # --- TOS check ---
    _check_and_prompt_tos()

    # Show current config so user knows their defaults
    from .config import list_values
    items = list_values()
    max_key = max((len(i["key"]) for i in items), default=0)
    max_val = max((len(str(i["value"] if i["value"] is not None else "-")) for i in items), default=0)
    print("  Your current settings:")
    for item in items:
        val = item["value"]
        display = str(val) if val is not None else "-"
        print(f"    {item['key']:<{max_key}}   {display:<{max_val}}   {item['description']}")
    print(f"\n  Run 'cartograph config <key> <value>' to change defaults.\n")

    out({"status": "success", "owner": handle})


def cmd_whoami(args):
    from .auth import is_authenticated
    if not is_authenticated():
        out({"authenticated": False})
        return
    from .cloud import whoami
    result = whoami()
    if "error" in result:
        err(result)
    out({"authenticated": True, **result})


def cmd_dashboard(args):
    if getattr(args, "stop", False):
        from .dashboard import stop
        if stop():
            print("\n  Dashboard stopped.\n")
        else:
            print("\n  No dashboard running.\n")
        return
    from .dashboard import serve, get_port, set_port
    if getattr(args, "set_port", None):
        set_port(args.set_port)
        print(f"\n  Dashboard port set to {args.set_port}.\n")
        return
    port = args.port if args.port != 0 else get_port()
    serve(_carto(), port=port)


def cmd_logout(args):
    from .auth import clear_token, is_authenticated
    if not is_authenticated():
        out({"status": "already_logged_out"})
        return
    clear_token()
    out({"status": "success", "message": "Logged out."})


def cmd_cloud_publish(args):
    from .auth import is_authenticated
    if not is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})

    if getattr(args, "lib", False):
        # Resolve path from library by widget_id
        widget_id = args.widget_id
        if not widget_id:
            err({"error": "Usage: cartograph cloud publish <widget_id> --lib"})
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
        if not widget:
            err({"error": f"Widget '{widget_id}' not found in library."})
        path = widget["path"]
    else:
        path = _resolve_widget(args.path)
        widget_id = args.widget_id
        # If widget_id was given but path is default ".", the user likely
        # ran `cartograph cloud publish <widget_id>` from outside the widget
        # dir. Try resolving the widget_id as a path or library lookup.
        if widget_id and args.path == "." and not os.path.isfile(os.path.join(path, "widget.json")):
            candidate = _resolve_widget(widget_id)
            if os.path.isfile(os.path.join(candidate, "widget.json")):
                path = candidate
            else:
                carto = _carto()
                lib_widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
                if lib_widget:
                    path = lib_widget["path"]
        if not widget_id:
            try:
                with open(os.path.join(path, "widget.json")) as f:
                    data = json.load(f)
                widget_id = data.get("meta", {}).get("id") or data.get("id")
            except Exception:
                pass
        if not widget_id:
            err({"error": "Could not determine widget_id. Pass it explicitly or use --lib."})

    _preflight_from_path(path)

    # Read widget.json once for stamp check + contamination scan
    try:
        with open(os.path.join(path, "widget.json")) as f:
            widget_data = json.load(f)
    except Exception:
        widget_data = {}
    tech_stack = widget_data.get("tech_stack", {})
    language = tech_stack.get("language", "python")

    # Ensure a valid stamp exists — run validation if not
    from .validation_stamp import is_stamp_valid
    from .languages import get_engine
    engine = get_engine(language)
    if engine is None or not is_stamp_valid(path, language, engine):
        print("  No valid stamp — running validation first...\n", file=sys.stderr)
        validate_result = _carto().validate_item(path=path)
        if validate_result.get("status") == "error":
            err(validate_result)

    # Contamination scan — same gate as checkin
    from .contamination import scan_contamination
    scan = scan_contamination(path)

    if scan["blocks"]:
        err({
            "error": "Push blocked: project-specific content detected.",
            "blocks": scan["blocks"],
        })

    if scan["warnings"] and not getattr(args, "override_warnings", False):
        err({
            "status": "warnings",
            "message": "Push paused: potential contamination found. "
                       "Review warnings and re-run with --override-warnings and --override-reason.",
            "warnings": scan["warnings"],
        })

    if getattr(args, "override_warnings", False) and not getattr(args, "override_reason", None):
        err({"error": "Push with --override-warnings requires --override-reason."})

    from .cloud import push
    from .config import load_config
    cfg = load_config()
    visibility = args.visibility or cfg["publish"]["visibility"]
    governance = getattr(args, "governance", None) or cfg["publish"]["governance"]

    # Sidecar first (own widget with established home), then publish-registry config fallback.
    # To change a widget's home registry: set publish-registry config, then cloud publish once.
    source = _read_source_meta(path)
    registry_url = source.get("registry_url") if source else _config_publish_registry_url()

    result = push(path, widget_id, visibility=visibility, governance=governance,
                  registry_url=registry_url)
    if "error" in result:
        err(result)

    nid      = result.get("namespaced_id", widget_id)
    version  = result.get("version", "?")
    vis      = result.get("visibility", "public")
    vis_icon = "🔒" if vis == "private" else "🌐"
    print(f"\n  ✓ Published {nid}  ·  v{version}  ·  {vis_icon} {vis}\n")


def cmd_rate(args):
    widget_id = args.widget_id

    # Cloud widget (@owner/prefix-widget-name)
    if widget_id.startswith("@"):
        from . import cloud, auth
        if not auth.is_authenticated():
            err({"error": "Not authenticated. Run: cartograph login"})
        owner, registry_url, bare_id = _parse_registry_id(widget_id)
        result = cloud.rate_widget(owner, bare_id, args.score, args.comment,
                                   registry_url=registry_url)
        if "error" in result:
            err(result)
        out({"status": "success", "widget_id": widget_id, "score": args.score})
        return

    # Local widget — requires dir path
    widget_id, target_dir, _ = _resolve_installed_widget(widget_id, os.getcwd())
    result = _carto().add_review(
        widget_id=widget_id,
        target_dir=target_dir,
        score=args.score,
        comment=args.comment,
    )
    if result.get("error"):
        err(result)
    out(result)


def cmd_cloud_adopt(args):
    """Link a local widget to its cloud counterpart by verifying src identity."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})

    local_id = args.local_id
    cloud_ref = args.cloud_id  # @owner/prefix-widget-name

    # Resolve local widget in library
    carto = _carto()
    widget = next((w for w in carto.widgets if w["id"] == local_id), None)
    if not widget:
        err({"error": f"Local widget '{local_id}' not found in library."})

    # Parse cloud reference
    parsed = _parse_registry_id(cloud_ref)
    if parsed is None:
        err({"error": f"Invalid cloud id '{cloud_ref}'. Use @owner/prefix-widget-name."})
    owner, registry_url, bare_id = parsed

    # Fetch cloud widget with source files for identity verification
    import tempfile

    print(f"  Fetching cloud widget {cloud_ref}...")
    cloud_widget = cloud.inspect(owner, bare_id, source=True, registry_url=registry_url)
    if "error" in cloud_widget:
        err(cloud_widget)

    # Server returns source files under "source" key (dict of rel_path -> content)
    cloud_files = cloud_widget.get("source") or cloud_widget.get("source_files", {})
    if not cloud_files:
        err({"error": "Cloud widget returned no source files. Cannot verify identity."})

    def _src_hash(base_path, files_dict=None):
        """Hash only src/ files. files_dict = {rel_path: content} for cloud, None for local."""
        import hashlib
        hasher = hashlib.md5()
        if files_dict is not None:
            for rel_path in sorted(files_dict.keys()):
                if rel_path.startswith("src/") or rel_path.startswith("src" + os.sep):
                    content = files_dict[rel_path]
                    data = content.encode() if isinstance(content, str) else content
                    hasher.update(data)
        else:
            src_path = os.path.join(base_path, "src")
            if os.path.exists(src_path):
                for root, dirs, files in os.walk(src_path):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for name in sorted(files):
                        if name.endswith(".pyc"):
                            continue
                        with open(os.path.join(root, name), "rb") as f:
                            hasher.update(f.read())
        return hasher.hexdigest()

    cloud_hash = _src_hash(None, cloud_files)
    local_hash = _src_hash(widget["path"])

    if cloud_hash != local_hash:
        # Report which src/ files differ
        local_src = set()
        p = os.path.join(widget["path"], "src")
        if os.path.exists(p):
            for root, _, files in os.walk(p):
                for f in files:
                    local_src.add(os.path.relpath(os.path.join(root, f), widget["path"]))
        cloud_src = {k for k in cloud_files.keys() if k.startswith("src/")}
        only_local = local_src - cloud_src
        only_cloud = cloud_src - local_src

        msg = ["Source files do not match - cannot adopt."]
        if only_local:
            msg.append(f"  Only local: {sorted(only_local)}")
        if only_cloud:
            msg.append(f"  Only cloud: {sorted(only_cloud)}")
        if not only_local and not only_cloud:
            msg.append("  Files are the same but content differs.")

        local_ver = widget.get("version", "?")
        cloud_ver = cloud_widget.get("version", "?")
        if local_ver != cloud_ver:
            msg.append(f"  Local v{local_ver} vs cloud v{cloud_ver}.")
            if local_ver > cloud_ver:
                msg.append("  Local is ahead - run: cartograph checkin --publish")
            else:
                msg.append("  Cloud is ahead - install the cloud version to get the latest.")

        err({"error": "\n".join(msg)})

    # Hashes match - write sidecar
    from .config import _PUBLIC_REGISTRY_URL
    sidecar = {
        "owner": owner,
        "registry_url": registry_url or _PUBLIC_REGISTRY_URL,
    }
    sidecar_path = os.path.join(widget["path"], ".cartograph_source")
    if os.path.exists(sidecar_path) and not args.force:
        try:
            with open(sidecar_path) as f:
                existing = json.load(f)
            err({
                "error": (
                    f"'{local_id}' already has a sidecar pointing to "
                    f"@{existing.get('owner', '?')} at {existing.get('registry_url', '?')}. "
                    f"Pass --force to overwrite."
                )
            })
        except Exception:
            pass  # unreadable sidecar - overwrite it
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f)

    cloud_ver = cloud_widget.get("version", "?")
    print(f"\n  Adopted: {local_id} linked to {cloud_ref} v{cloud_ver}")
    print(f"  Future checkin --publish will route to {sidecar['registry_url']}\n")


def cmd_cloud_unpublish(args):
    """Remove a widget from the cloud registry (keeps local copy)."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})
    if not getattr(args, "confirm", False):
        err({"error": f"This will remove '{args.widget_id}' from the cloud registry. Pass --confirm to proceed."})
    parsed = _parse_registry_id(args.widget_id)
    if parsed:
        owner, registry_url, bare_id = parsed
        result = cloud.delete_widget(bare_id, registry_url=registry_url)
    else:
        # Bare widget_id - look up sidecar from library, fall back to publish-registry config
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == args.widget_id), None)
        source = _read_source_meta(widget["path"]) if widget else None
        registry_url = source.get("registry_url") if source else _config_publish_registry_url()
        result = cloud.delete_widget(args.widget_id, registry_url=registry_url)
    if "error" in result:
        err(result)
    print(f"\n  Unpublished {args.widget_id} from cloud. Local copy unchanged.\n")



def cmd_rollback(args):
    """Roll back a widget to a previous version (local and/or cloud)."""
    from . import cloud, auth
    from .checkin import restore

    widget_id = args.widget_id
    version = args.version

    # Determine if this is a cloud widget (@owner/prefix-id) or local
    owner_handle = None
    registry_url = None
    base_id = widget_id
    if widget_id.startswith("@"):
        parsed = _parse_registry_id(widget_id)
        if parsed:
            owner_handle, registry_url, base_id = parsed
        else:
            err({"error": f"Invalid format: '{widget_id}'. Use @owner/prefix-widget-id."})

    carto = _carto()

    # If no version specified, list available versions
    if not version:
        if owner_handle:
            # Cloud: list versions from GCS
            result = cloud.get_versions(owner_handle, base_id, registry_url=registry_url)
            if "error" in result:
                err(result)
            versions = result.get("versions", [])
            current = result.get("current_version", "?")
            if not versions:
                err({"error": f"No versions found for {widget_id}"})
            print(f"\n  Versions for {widget_id} (current: {current}):\n")
            for v in versions:
                marker = " ← current" if v == current else ""
                print(f"    {v}{marker}")
            print()
        else:
            # Local: list from history/
            item = next((w for w in carto.widgets if w["id"] == base_id), None)
            if not item:
                err({"error": f"Widget '{base_id}' not found in library"})
            import os
            history_dir = os.path.join(item["path"], "history")
            if not os.path.isdir(history_dir):
                err({"error": f"No version history for '{base_id}'"})
            versions = sorted(os.listdir(history_dir), reverse=True)
            current = item.get("version", "?")
            if not versions:
                err({"error": f"No version history for '{base_id}'"})
            print(f"\n  Versions for {base_id} (current: {current}):\n")
            for v in versions:
                marker = " ← current" if v == current else ""
                print(f"    {v}{marker}")
            print(f"\n  Run: cartograph rollback {base_id} --version <version>\n")
        return

    # Perform rollback
    rolled_local = False
    rolled_cloud = False

    # Local rollback (if widget exists locally)
    local_widget = next((w for w in carto.widgets if w["id"] == base_id), None)
    if local_widget:
        result = restore(carto, base_id, version, reason=args.reason or f"Rollback to v{version}")
        if result.get("status") == "error" or "error" in result:
            print(f"  Local rollback failed: {result.get('message', 'unknown error')}")
        else:
            rolled_local = True
            new_version = result.get("version", "?")
            print(f"  ✓ Local: rolled back to v{version} (now v{new_version})")

    # Cloud rollback (if @handle/id or widget is published)
    if owner_handle:
        result = cloud.rollback_widget(owner_handle, base_id, version, registry_url=registry_url)
        if "error" in result:
            print(f"  Cloud rollback failed: {result.get('error', 'unknown error')}")
        else:
            rolled_cloud = True
            nv = result.get('new_version', '?')
            print(f"  ✓ Cloud: restored v{version} as v{nv} (was v{result.get('previous_version', '?')})")
    elif auth.is_authenticated():
        # Check if widget exists on cloud using sidecar registry if available
        local_sidecar = {}
        local_w = next((w for w in carto.widgets if w["id"] == base_id), None)
        if local_w:
            try:
                with open(os.path.join(local_w["path"], ".cartograph_source")) as f:
                    local_sidecar = json.load(f)
            except Exception:
                pass
        sidecar_owner = local_sidecar.get("owner", "")
        sidecar_reg = local_sidecar.get("registry_url") or None
        check_owner = sidecar_owner or cloud.whoami().get("owner", "")
        info = cloud.inspect(check_owner, base_id, registry_url=sidecar_reg)
        if "error" not in info:
            owner = info.get("owner", check_owner)
            result = cloud.rollback_widget(owner, base_id, version, registry_url=sidecar_reg)
            if "error" in result:
                print(f"  Cloud rollback failed: {result.get('error', 'unknown error')}")
            else:
                rolled_cloud = True
                nv = result.get('new_version', '?')
                print(f"  ✓ Cloud: restored v{version} as v{nv} (was v{result.get('previous_version', '?')})")

    if not rolled_local and not rolled_cloud:
        err({"error": f"Could not rollback '{widget_id}' — not found locally or on cloud"})

    print()


def _parse_cloud_id(widget_id: str):
    """Parse @handle/widget_id into (owner, widget_id). Calls err() on bad format."""
    if not widget_id.startswith("@"):
        err({"error": f"Expected @owner/widget_id format, got '{widget_id}'"})
    parts = widget_id[1:].split("/", 1)
    if len(parts) != 2:
        err({"error": f"Invalid format: '{widget_id}'. Use @owner/widget_id."})
    return parts[0], parts[1]


def cmd_cloud_settings(args):
    """View or update a cloud widget's settings."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})

    parsed = _parse_registry_id(args.widget_id)
    if parsed:
        owner, registry_url, wid = parsed
    else:
        owner, wid = _parse_cloud_id(args.widget_id)
        registry_url = None

    visibility = getattr(args, "visibility", None)
    governance = getattr(args, "governance", None)

    # If no flags, show current settings
    if not governance and not visibility:
        result = cloud.inspect(owner, wid, registry_url=registry_url)
        if "error" in result:
            err(result)
        gov = result.get("governance", "-")
        vis = result.get("visibility", "-")
        print(f"\n  @{owner}/{wid}")
        print(f"    governance   {gov}")
        print(f"    visibility   {vis}")
        print(f"\n  Use --governance open|protected or --visibility public|private to change.\n")
        return

    kwargs = {}
    if governance:
        kwargs["governance"] = governance
    if visibility:
        kwargs["visibility"] = visibility

    result = cloud.update_widget(owner, wid, registry_url=registry_url, **kwargs)
    if "error" in result:
        err(result)

    changed = []
    if governance:
        changed.append(f"governance = {governance}")
    if visibility:
        changed.append(f"visibility = {visibility}")
    print(f"\n  Updated @{owner}/{wid}: {', '.join(changed)}\n")


def cmd_cloud_proposals(args):
    """List, accept, or reject proposals."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})

    proposal_id = getattr(args, "proposal_id", None)

    # No ID -> list my proposals
    if not proposal_id:
        result = cloud.my_proposals()
        if "error" in result:
            err(result)
        proposals = result.get("proposals", [])
        if not proposals:
            print("\n  No proposals.\n")
            return
        print()
        for p in proposals:
            status = p.get("status", "pending")
            widget = p.get("widget_id", "?")
            owner = p.get("owner", "?")
            pid = p.get("id", "?")
            submitter = p.get("submitter_handle", "?")
            version = p.get("version", "?")
            summary = p.get("diff_summary") or {}
            ins = summary.get("insertions", 0)
            dels = summary.get("deletions", 0)
            changed = len(summary.get("files_modified", [])) + len(summary.get("files_added", [])) + len(summary.get("files_deleted", []))
            wj = " widget.json" if summary.get("widget_json_changed") else ""
            print(f"  [{status}]  @{owner}/{widget}  #{pid}")
            print(f"            from @{submitter}  v{version}  {changed} file(s), +{ins}/-{dels}{wj}")
        print(f"\n  View:   cartograph cloud proposals <widget_id> <id>")
        print(f"  Diff:   cartograph cloud proposals <widget_id> <id> --diff")
        print(f"  Decide: cartograph cloud proposals <widget_id> <id> --accept | --reject --reason \"...\"\n")
        return

    # Accept, reject, or view
    parsed = _parse_registry_id(args.widget_id)
    if parsed:
        owner, registry_url, wid = parsed
    else:
        owner, wid = _parse_cloud_id(args.widget_id)
        registry_url = None
    if getattr(args, "diff", False):
        result = cloud.proposal_diff(owner, wid, proposal_id, registry_url=registry_url)
        if "error" in result:
            err(result)
        print(result.get("diff", ""))
    elif getattr(args, "accept", False):
        result = cloud.accept_proposal(owner, wid, proposal_id, registry_url=registry_url)
        if "error" in result:
            err(result)
        print(f"\n  Proposal #{proposal_id} accepted.\n")
    elif getattr(args, "reject", False):
        reason = getattr(args, "reason", "")
        result = cloud.reject_proposal(owner, wid, proposal_id, reason=reason, registry_url=registry_url)
        if "error" in result:
            err(result)
        print(f"\n  Proposal #{proposal_id} rejected.\n")
    else:
        # Just viewing a specific proposal
        result = cloud.list_proposals(owner, wid, registry_url=registry_url)
        if "error" in result:
            err(result)
        proposals = result.get("proposals", [])
        match = next((p for p in proposals if str(p.get("id")) == str(proposal_id)), None)
        if not match:
            err({"error": f"Proposal #{proposal_id} not found."})
        out(match)


def _rules_dir_for_scope(scope: str) -> str:
    if scope == "global":
        from .engine import _user_data_dir
        return os.path.join(_user_data_dir(), "rules")
    return os.path.join(os.getcwd(), ".cartograph", "rules")


def cmd_rules(args):
    """List, read, or write custom validation rules.

    Actions: (none) list | init | get | write | reset.
    All actions accept --json for structured output so the MCP layer can
    drive the rules surface. `get` and `write` are the read/write pair an
    agent uses to codify project conventions.
    """
    action = getattr(args, "action", None)
    as_json = getattr(args, "as_json", False)

    if action == "get":
        from .rules import get_rules_filename
        language = getattr(args, "language", None)
        scope = getattr(args, "scope", "project")
        if not language:
            err({"error": "Usage: cartograph rules get --language python [--global]"})
        filename = get_rules_filename(language)
        if not filename:
            err({"error": f"No rules support for language '{language}'"})
        filepath = os.path.join(_rules_dir_for_scope(scope), filename)
        if not os.path.exists(filepath):
            err({"error": f"No rules file at {filepath}. Run 'cartograph rules init --language {language}" + (" --global" if scope == "global" else "") + "' to create one."})
        with open(filepath) as f:
            content = f.read()
        if as_json:
            out({"status": "success", "language": language, "scope": scope, "path": filepath, "content": content})
            return
        print(f"\n  {filepath}\n")
        print(content)
        return

    if action == "write":
        from .rules import get_rules_filename
        language = getattr(args, "language", None)
        scope = getattr(args, "scope", "project")
        content = getattr(args, "content", None)
        from_file = getattr(args, "from_file", None)
        confirm = getattr(args, "confirm", False)
        if not language:
            err({"error": "Usage: cartograph rules write --language python [--global] --content '<rules>' | --from-file <path>"})
        filename = get_rules_filename(language)
        if not filename:
            err({"error": f"No rules support for language '{language}'"})
        if from_file:
            try:
                with open(from_file) as f:
                    content = f.read()
            except OSError as e:
                err({"error": f"Could not read {from_file}: {e}"})
        elif content is None:
            # Read from stdin when neither --content nor --from-file given;
            # makes shell piping work cleanly (cat rules.py | cartograph rules write ...)
            import sys as _sys
            if _sys.stdin.isatty():
                err({"error": "Provide content via --content, --from-file, or stdin."})
            content = _sys.stdin.read()

        rules_dir = _rules_dir_for_scope(scope)
        filepath = os.path.join(rules_dir, filename)
        if os.path.exists(filepath) and not confirm:
            err({"error": f"Rules file already exists at {filepath}. Re-run with --confirm to overwrite."})
        os.makedirs(rules_dir, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
        if as_json:
            out({"status": "success", "language": language, "scope": scope, "path": filepath, "bytes": len(content)})
            return
        print(f"\n  Wrote {len(content)} bytes to {filepath}\n")
        return

    if action == "reset":
        language = getattr(args, "language", None)
        scope = getattr(args, "scope", "project")

        if not language:
            err({"error": "Usage: cartograph rules reset --language python [--global]"})

        from .rules import get_template, get_rules_filename
        filename = get_rules_filename(language)
        if not filename:
            err({"error": f"No rules support for language '{language}'"})

        rules_dir = _rules_dir_for_scope(scope)
        filepath = os.path.join(rules_dir, filename)
        if not os.path.exists(filepath):
            err({"error": f"No rules file at {filepath}. Run 'cartograph rules init --language {language}" + (" --global" if scope == "global" else "") + "' to create one."})

        confirm = getattr(args, "confirm", False)
        if not confirm:
            err({"error": f"This would overwrite your custom rules at {filepath}. Re-run with --confirm to proceed."})

        template = get_template(language)
        with open(filepath, "w") as f:
            f.write(template)

        if as_json:
            out({"status": "success", "language": language, "scope": scope, "path": filepath, "action": "reset"})
            return
        print(f"\n  Reset to default template: {filepath}\n")
        return

    if action == "init":
        language = getattr(args, "language", None)
        scope = getattr(args, "scope", "project")

        if not language:
            err({"error": "Usage: cartograph rules init --language python [--global]"})

        from .rules import get_template, get_rules_filename
        filename = get_rules_filename(language)
        if filename is None:
            err({"error": f"No rules support for language '{language}'"})

        template = get_template(language)
        if template is None:
            err({"error": f"No rules template for language '{language}'"})

        rules_dir = _rules_dir_for_scope(scope)
        os.makedirs(rules_dir, exist_ok=True)
        filepath = os.path.join(rules_dir, filename)

        already_existed = os.path.exists(filepath)
        if not already_existed:
            with open(filepath, "w") as f:
                f.write(template)

        if as_json:
            out({
                "status": "success",
                "language": language,
                "scope": scope,
                "path": filepath,
                "created": not already_existed,
            })
            return
        if already_existed:
            print(f"\n  Rules file already exists: {filepath}")
            print(f"  Open it in your editor to add or modify checks.\n")
        else:
            print(f"\n  Created: {filepath}")
            print(f"  Open it in your editor and uncomment or add checks.")
            print(f"  It runs automatically during `cartograph validate`.\n")
        return

    # Default: list rules files
    from .rules import find_rules

    rules = find_rules()
    if as_json:
        out({"status": "success", "rules": rules})
        return
    print()
    print("  Rules run automatically during `cartograph validate` and `cartograph checkin`.")
    print()
    if rules:
        for r in rules:
            print(f"  {r['language']:<14} {r['scope']:<10} {r['path']}")
        print()
        print("  Global rules: open any path above in your editor to add or modify checks.")
        print()
        print("  Project rules (per-repo, checked in with your project):")
        print("    cartograph rules init --language <lang>")
    else:
        print("  No custom rules found.")
        print()
        print("  Initialize one with:")
        print("    cartograph rules init --language python")
        print("    cartograph rules init --language python --global")
    print()


def cmd_workflow(args):
    """List or create workflows."""
    name = getattr(args, "name", None)
    source = getattr(args, "source", None)

    from .engine import _user_data_dir
    workflows_dir = os.path.join(_user_data_dir(), "workflows")

    if not name:
        # List available workflows
        print("\n  Available workflows:")
        print(f"    {'default':<14} (built-in)")
        if os.path.isdir(workflows_dir):
            for f in sorted(os.listdir(workflows_dir)):
                if f.endswith(".md"):
                    wf_name = f[:-3]
                    wf_path = os.path.join(workflows_dir, f)
                    print(f"    {wf_name:<14} {wf_path}")
        print(f"\n  Use with: cartograph setup --workflow <name>\n")
        return

    if name == "create":
        # workflow create <actual_name> <source_file>
        actual_name = source
        source_file = getattr(args, "extra", None)
        if not actual_name or not source_file:
            err({"error": "Usage: cartograph workflow create <name> <file.md>"})
        source_file = os.path.abspath(source_file)
        if not os.path.isfile(source_file):
            err({"error": f"File not found: {source_file}"})
        os.makedirs(workflows_dir, exist_ok=True)
        dest = os.path.join(workflows_dir, f"{actual_name}.md")
        shutil.copy2(source_file, dest)
        print(f"\n  Saved workflow '{actual_name}' to {dest}\n")
        return

    # Show a specific workflow
    if name == "default":
        print(_WORKFLOW_SECTION)
        return
    path = os.path.join(workflows_dir, f"{name}.md")
    if not os.path.isfile(path):
        err({"error": f"Workflow '{name}' not found. Run 'cartograph workflow' to list."})
    with open(path) as f:
        print(f"\n{f.read()}")


def cmd_doctor(args):
    import shutil
    import subprocess

    groups = []  # list of (group_name, [(label, ok, detail, fix), ...])

    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except Exception as e:
            return False, str(e)

    # --- Platform ---
    import platform
    plat_checks = []
    plat_checks.append(("OS", True, f"{platform.system()} {platform.release()}", None))
    plat_checks.append(("Arch", True, platform.machine(), None))
    groups.append(("Platform", plat_checks))

    # --- Library (auto-setup if missing) ---
    from .engine import LIBRARY_PATH, _ensure_library
    lib_checks = []
    if not os.path.isdir(LIBRARY_PATH):
        try:
            _ensure_library(LIBRARY_PATH)
            lib_checks.append(("Library", True, f"Created at {LIBRARY_PATH}", None))
        except Exception as e:
            lib_checks.append(("Library", False, str(e), "Check disk permissions"))
    else:
        lib_checks.append(("Library", True, LIBRARY_PATH, None))
    groups.append(("Library", lib_checks))

    # --- Cloud registry ---
    from .cloud import is_available as _cloud_available
    from .auth import get_registry_url
    cloud_checks = []
    url = get_registry_url()
    if _cloud_available():
        cloud_checks.append(("Registry", True, url, None))
    else:
        cloud_checks.append(("Registry", False, f"unreachable - {url}", "Check network or CARTOGRAPH_REGISTRY_URL"))
    groups.append(("Cloud", cloud_checks))

    # --- Language engines (auto-discovered) ---
    from .languages.registry import _ENGINES
    _lang_order = {"python": 0, "javascript": 1, "typescript": 2, "nim": 3, "openscad": 4, "angular": 5, "php": 6}
    lang_checks = []
    for lang_name, engine in sorted(_ENGINES.items(), key=lambda x: _lang_order.get(x[0], 99)):
        available, message = engine.check_available()
        ev = getattr(engine, "validation_version", None)
        rv = engine.runtime_version() if available else None
        tags = []
        if ev is not None:
            tags.append(f"engine v{ev}")
        if rv:
            tags.append(rv)
        tag_str = f"  ({', '.join(tags)})" if tags else ""
        if available:
            lang_checks.append((lang_name, True, f"ready{tag_str}", None))
            for binary in getattr(engine, "toolchain", {}) or {}:
                try:
                    resolved = engine.resolved_binary(binary)
                except Exception:
                    resolved = None
                if resolved and resolved.source == "override":
                    lang_checks.append(
                        (f"  {binary}", True,
                         f"{resolved.path} (paths.{binary})", "optional"))
            for label, installed, detail in engine.check_optional():
                if not installed:
                    lang_checks.append((label, False, detail, "optional"))
        else:
            lang_checks.append((lang_name, False, f"not ready{tag_str}", message))
    groups.append(("Languages", lang_checks))

    # --- Render ---
    use_color = sys.stdout.isatty()
    green = "\033[32m" if use_color else ""
    red = "\033[31m" if use_color else ""
    yellow = "\033[33m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    required_checks = [c for _, checks in groups for c in checks if c[3] != "optional"]
    passed = sum(1 for c in required_checks if c[1])
    total = len(required_checks)
    all_ok = passed == total

    print()
    for group_name, checks in groups:
        all_group_ok = all(c[1] for c in checks if c[3] != "optional")
        gc = green if all_group_ok else red
        print(f"  {gc}{group_name}{reset}")
        for label, ok, detail, fix in checks:
            if fix == "optional":
                c = green if ok else yellow
                mark = "✓" if ok else "i"
                print(f"    {c}[{mark}]{reset} {label:<12}  {detail}")
            else:
                c = green if ok else red
                mark = "✓" if ok else "✗"
                print(f"    {c}[{mark}]{reset} {label:<12}  {detail}")
                if not ok and fix:
                    print(f"          {red}-> {fix}{reset}")
        print()

    if all_ok:
        print(f"  {green}No issues found.{reset}\n")
    else:
        issues = total - passed
        print(f"  {red}{issues} issue{'s' if issues > 1 else ''} found.{reset}\n")
        sys.exit(1)


def _build_setup_instructions() -> str:
    import json as _json
    _cfg_path = os.path.join(os.path.dirname(__file__), "library_config.json")
    try:
        with open(_cfg_path) as _f:
            cfg = _json.load(_f)
    except Exception:
        cfg = {}
    domains = cfg.get("domains", {})
    domain_lines = "\n".join(
        f"    {name:<10} {desc.split('.')[0].strip()}"
        for name, desc in domains.items()
    )

    from .config import _SCHEMA, _DEFAULTS
    _flat_defaults = {k: v for section in _DEFAULTS.values() for k, v in section.items()}
    # Map toml_key back to CLI key for defaults lookup
    _toml_to_cli = {meta[1]: key for key, meta in _SCHEMA.items()}
    config_lines = "\n".join(
        f"    {key:<18} {meta[4]}  (default: {_flat_defaults.get(meta[1], '—')})"
        for key, meta in _SCHEMA.items()
    )

    return f"""\
## Cartograph

Widget library manager. Widgets are reusable code modules with tests,
examples, and metadata. Installed widgets live under `cg/<widget_id>/`.

widget_id format: `<domain>-<name>-<language>` (e.g. `backend-retry-backoff-python`)

When using `cartograph create`, only provide the name. The `--domain` and
`--language` flags are prepended and appended automatically.
Example: `cartograph create retry-backoff --domain backend --language python`
creates `backend-retry-backoff-python`.

### Domains

{domain_lines}

### Config keys  (set with: cartograph config <key> <value>)

{config_lines}"""


_COMMANDS_HEADER = """

### Commands

All commands run from your project root. Widgets install to `cg/` in the
current directory (or the directory specified by `--target`).

"""


def _dogfood_widget_file(widget_dir_name: str, module_file: str) -> str:
    """Resolve a dogfooded widget's source file in both install layouts.

    Dev/editable:  <repo>/src/cartograph/cli.py  → ../../cg/<widget>/src/<module>
    Wheel install: site-packages/cartograph/cli.py → ../cg/<widget>/src/<module>

    Hatch packages `cg/` alongside `cartograph/` at wheel root, so the walk is
    one level shorter once installed. Returns the first candidate that exists;
    returns the last candidate if neither does so the caller gets a sensible
    path in the FileNotFoundError.
    """
    here = os.path.dirname(__file__)
    candidates = [
        os.path.join(here, "..", "..", "cg", widget_dir_name, "src", module_file),
        os.path.join(here, "..", "cg", widget_dir_name, "src", module_file),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[-1]


_CATALOG_FN = None


def _catalog_widget():
    """Dogfooded infra-command-catalog-python widget, loaded by file path to
    sidestep the `src/` namespace collision with this repo's own src/cartograph/."""
    global _CATALOG_FN
    if _CATALOG_FN is not None:
        return _CATALOG_FN
    import importlib.util
    widget_file = _dogfood_widget_file("infra_command_catalog_python", "command_catalog.py")
    spec = importlib.util.spec_from_file_location("_cg_command_catalog", widget_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _CATALOG_FN = module.Catalog
    return _CATALOG_FN


def _replace_cartograph_section(existing: str, new_content: str) -> str:
    """Splice `new_content` into `existing` in place of the ## Cartograph section.

    The owned section starts at the first line that is exactly `## Cartograph`
    and ends at the next line that begins with `## ` (a peer heading) or EOF.
    Everything outside that range is preserved byte-for-byte.
    """
    lines = existing.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "## Cartograph":
            start = i
            break
    if start is None:
        # Safety net: marker went missing between check and splice; just append.
        return existing.rstrip() + "\n\n" + new_content.lstrip()
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and lines[i].rstrip() != "## Cartograph":
            end = i
            break
    before = "".join(lines[:start])
    after = "".join(lines[end:])
    new_block = new_content.lstrip("\n")
    if before and not before.endswith("\n"):
        before += "\n"
    if not new_block.endswith("\n"):
        new_block += "\n"
    return before + new_block + ("\n" + after if after else "")


def _render_commands_block() -> str:
    """Build the ### Commands section from the live CLI registration.

    Reads groups off the AgentCLI after it's built, so there is exactly one
    source of truth for command metadata. Adding a new command via
    `cli.add_commands(...)` also adds it to the agent-facing documentation
    with no extra step.
    """
    cli = _build_cli()
    sections = {name: cmds for name, cmds in cli._groups}
    Catalog = _catalog_widget()
    return _COMMANDS_HEADER + Catalog(sections).to_agent_instructions()

_WORKFLOW_SECTION = """
### Workflow

Think in terms of widgets. Need to add capability, search for a widget.

If you are adding a feature always consider whether it can be added into an existing widget. If not, consider if it could be added as a new widget.
Only project specific wiring should not be made into widgets.

1. Plan what components you need before building
2. Decide whether new implementation can just be an improvement on currently used widgets. Read the widgets before deciding.
3. Search the library before writing new logic
4. Install widgets, then write glue code to connect them. Don't edit widget source directly for this step.
5. If you do edit a widget, only do so if you intend to check it back in as an improvement for the general logic of the widget.
6. Validate before checking in, check in before publishing

Definition of reusable code: Any code that would be written for another project. A lot of code may look "project specific" but if you peel back the logic you will realize it can be used across many projects. These are the widgets that need to be extracted, or made.
"""

_AGENT_FILENAMES = {
    "claude":       "CLAUDE.md",
    "codex":        "AGENTS.md",
    "agents":       "AGENTS.md",
    "gemini":       "GEMINI.md",
    "antigravity":  "GEMINI.md",
    "cursor":       os.path.join(".cursor", "rules", "cartograph.mdc"),
}

_AGENT_GENERIC_FILE = "AGENTS.md"


def _detect_agent(directory: str) -> tuple[str | None, str | None]:
    """Auto-detect which AI agent is in use.

    Returns (agent_name, reason) or (None, None) if nothing detected.
    Detection order: env vars (authoritative during active session) first,
    then per-project markers. Codex is intentionally not autodetected - it
    does not set a subprocess env var (see openai/codex#13416), and AGENTS.md
    is the generic cross-agent convention, not codex-specific. Users who
    want codex-specific setup pass --agent codex.
    """
    if os.environ.get("CLAUDECODE") == "1":
        return "claude", "CLAUDECODE env var"
    if os.environ.get("GEMINI_CLI") == "1":
        return "gemini", "GEMINI_CLI env var"
    if os.path.isdir(os.path.join(directory, ".claude")):
        return "claude", ".claude/ directory"
    if os.path.isfile(os.path.join(directory, "CLAUDE.md")):
        return "claude", "CLAUDE.md"
    if os.path.isdir(os.path.join(directory, ".cursor")):
        return "cursor", ".cursor/ directory"
    if os.path.isfile(os.path.join(directory, "GEMINI.md")):
        return "gemini", "GEMINI.md"
    if os.path.isfile(os.path.join(directory, "AGENTS.md")):
        return "agents", "AGENTS.md"
    return None, None





def cmd_export(args):
    """Export the widget library as a zip file."""
    import zipfile
    from .engine import LIBRARY_PATH

    if not os.path.isdir(LIBRARY_PATH):
        err({"error": "No widget library found."})

    output = args.output or "cartograph-library.zip"
    if not output.endswith(".zip"):
        output += ".zip"

    skip = {"__pycache__", ".pytest_cache", "node_modules"}

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(LIBRARY_PATH):
            dirs[:] = [d for d in dirs if d not in skip]
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                full = os.path.join(root, fname)
                arcname = os.path.relpath(full, LIBRARY_PATH)
                zf.write(full, arcname)

    size_mb = os.path.getsize(output) / (1024 * 1024)
    carto = _carto()
    print(f"\n  Exported {len(carto.widgets)} widgets to {output} ({size_mb:.1f} MB)\n")


def cmd_import(args):
    """Import a widget library from a zip file."""
    import zipfile
    from .engine import LIBRARY_PATH

    path = args.path
    if not os.path.isfile(path):
        err({"error": f"File not found: {path}"})

    if not zipfile.is_zipfile(path):
        err({"error": f"Not a valid zip file: {path}"})

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        # Verify it looks like a widget library (has at least one widget.json)
        manifests = [n for n in names if n.endswith("widget.json") and n.count("/") == 1]
        if not manifests:
            err({"error": "Zip does not appear to contain a widget library (no widget.json files found)."})

        os.makedirs(LIBRARY_PATH, exist_ok=True)

        imported = 0
        skipped = 0
        for name in names:
            dest = os.path.join(LIBRARY_PATH, name)
            if name.endswith("/"):
                os.makedirs(dest, exist_ok=True)
                continue
            # Don't overwrite existing files unless --force
            if os.path.exists(dest) and not getattr(args, "force", False):
                skipped += 1
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            imported += 1

    # Reload to pick up new widgets
    carto = _carto()
    print(f"\n  Imported {imported} files ({len(manifests)} widgets). {skipped} files skipped (already exist).")
    if skipped:
        print(f"  Re-run with --force to overwrite existing files.")
    print()


def cmd_stats(args):
    from collections import defaultdict
    widgets = _carto().widgets

    if not widgets:
        out({"status": "success", "widget_count": 0, "message": "Library is empty."})
        return

    by_language = defaultdict(int)
    by_domain   = defaultdict(int)
    rated       = []
    installed   = []

    for w in widgets:
        lang = w.get("language", "unknown")
        if isinstance(lang, list):
            lang = lang[0] if lang else "unknown"
        by_language[lang] += 1
        by_domain[w.get("domain", "unknown")] += 1

        if w.get("rating", 0):
            rated.append({"name": w["name"], "rating": w["rating"]})
        if w.get("install_count", 0):
            installed.append({"name": w["name"], "installs": w["install_count"]})

    rated.sort(key=lambda x: x["rating"], reverse=True)
    installed.sort(key=lambda x: x["installs"], reverse=True)

    all_ratings = [w.get("rating", 0) for w in widgets if w.get("rating", 0)]
    avg_rating  = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0
    total_installs = sum(w.get("install_count", 0) for w in widgets)

    out({
        "status": "success",
        "widget_count": len(widgets),
        "total_installs": total_installs,
        "avg_rating": avg_rating,
        "by_language": dict(sorted(by_language.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "most_installed": installed[:5],
        "top_rated": rated[:5],
    })


def cmd_sync(args):
    """Reconcile local library with cloud. Local newer → push, cloud newer → download."""
    from . import cloud, auth
    from .engine import semver_key as _semver_key

    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})
    if not cloud.is_available():
        err({"error": "Cloud registry is unreachable."})

    dry_run = args.dry_run
    carto = _carto()
    local_widgets = {w["id"]: w for w in carto.widgets}

    profile = cloud.whoami()
    if "error" in profile:
        err(profile)
    handle = profile.get("owner", "")

    cloud_widgets_list = cloud.list_my_widgets()
    if not cloud_widgets_list:
        print("\n  No widgets published to cloud. Use 'cartograph cloud publish' first.\n")
        return
    # Cloud IDs are @owner/widget-id; normalize to bare widget-id for matching
    def _bare(wid):
        return wid.split("/", 1)[1] if "/" in wid else wid
    cloud_by_id = {_bare(w["id"]): w for w in cloud_widgets_list}

    all_ids = sorted(set(local_widgets) | set(cloud_by_id))
    if not all_ids:
        print("\n  Nothing to sync — library and cloud are both empty.\n")
        return

    _ver = _semver_key

    actions = []  # (widget_id, action, detail)
    for wid in all_ids:
        local = local_widgets.get(wid)
        remote = cloud_by_id.get(wid)

        if local and not remote:
            actions.append((wid, "local_only", local.get("version", "?")))
            continue
        if remote and not local:
            actions.append((wid, "pull", remote.get("version", "?")))
            continue

        lv = _ver(local.get("version", "0.0.0"))
        rv = _ver(remote.get("version", "0.0.0"))
        if lv > rv:
            actions.append((wid, "push", f"{lv} → {rv}"))
        elif rv > lv:
            actions.append((wid, "pull", f"{rv} → {lv}"))
        else:
            actions.append((wid, "ok", str(lv)))

    # Print plan
    pushes = [(w, d) for w, a, d in actions if a == "push"]
    pulls = [(w, d) for w, a, d in actions if a == "pull"]
    synced = [(w, d) for w, a, d in actions if a == "ok"]
    local_only = [(w, d) for w, a, d in actions if a == "local_only"]

    print()
    if synced:
        print(f"  In sync     {len(synced)}")
    if local_only:
        print(f"  Local only  {len(local_only)}  (not published — skipping)")
    if pushes:
        print(f"  Push        {len(pushes)}  (local is newer)")
        for wid, detail in pushes:
            print(f"    {wid}  {detail}")
    if pulls:
        print(f"  Pull        {len(pulls)}  (cloud is newer)")
        for wid, detail in pulls:
            print(f"    {wid}  {detail}")
    print()

    if not pushes and not pulls:
        print("  Everything is in sync.\n")
        return

    if dry_run:
        print("  Dry run — no changes made.\n")
        return

    # Execute pushes
    for wid, detail in pushes:
        w = local_widgets[wid]
        print(f"  Pushing {wid}...", end=" ", flush=True)
        result = cloud.push(w["path"], wid)
        if result.get("error"):
            print(f"FAILED: {result['error']}")
        else:
            print(f"ok → v{result.get('version', '?')}")

    # Execute pulls — download and extract into library
    for wid, detail in pulls:
        remote = cloud_by_id[wid]
        owner = remote.get("owner", handle)
        print(f"  Pulling {wid}...", end=" ", flush=True)
        result = cloud.download_widget(owner, wid)
        if "error" in result:
            print(f"FAILED: {result['error']}")
            continue
        # Extract into library, overwriting existing
        dest = os.path.join(carto.library_path, wid)
        try:
            if os.path.exists(dest):
                shutil.rmtree(dest)
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(BytesIO(result["zip_bytes"])) as zf:
                zf.extractall(dest)
            print(f"ok → v{result.get('version', '?')}")
        except Exception as e:
            print(f"FAILED: {e}")

    print()


def _cursor_mdc(content):
    """Wrap plain markdown content in Cursor's MDC frontmatter format."""
    return (
        "---\n"
        "description: Cartograph widget library usage rules\n"
        "alwaysApply: true\n"
        "---\n\n"
    ) + content


def _resolve_workflow(workflow_arg):
    """Resolve --workflow flag to markdown content.

    None          -> no workflow
    "default"/""  -> built-in _WORKFLOW_SECTION
    "<name>"      -> load from <data_dir>/workflows/<name>.md
    """
    if workflow_arg is None:
        return ""
    if not workflow_arg or workflow_arg == "default":
        return _WORKFLOW_SECTION

    from .engine import _user_data_dir
    path = os.path.join(_user_data_dir(), "workflows", f"{workflow_arg}.md")
    if not os.path.isfile(path):
        workflows_dir = os.path.join(_user_data_dir(), "workflows")
        available = []
        if os.path.isdir(workflows_dir):
            available = [f[:-3] for f in os.listdir(workflows_dir) if f.endswith(".md")]
        msg = f"Workflow '{workflow_arg}' not found at {path}."
        if available:
            msg += f" Available: {', '.join(sorted(available))}"
        else:
            msg += f" Create it at: {workflows_dir}/{workflow_arg}.md"
        err({"error": msg})
    with open(path) as f:
        return "\n" + f.read()


def cmd_setup(args):
    agent = getattr(args, "agent", None)
    print_only = getattr(args, "print", False)
    custom_file = getattr(args, "file", None)
    target_dir = os.getcwd()

    # --- Resolve agent ---
    detected_reason = None
    if not agent:
        agent, detected_reason = _detect_agent(target_dir)

    if not agent and not custom_file:
        if print_only:
            # No agent needed for --print, just show the content
            agent = None
        else:
            print("\n  Could not auto-detect agent (no .claude/, .cursor/, AGENTS.md, or GEMINI.md found).")
            print()
            print("  Options:")
            print("    cartograph setup --agent claude       specify agent explicitly")
            print("    cartograph setup --file instructions.md   write to a custom file")
            print()
            print(f"  Or write a generic AGENTS.md (cross-agent convention):")
            print(f"    cartograph setup --agent agents")
            print()
            return

    # --- Build content ---
    content = _build_setup_instructions() + _render_commands_block()
    content += _resolve_workflow(getattr(args, "workflow", None))

    # --- Resolve target file ---
    if custom_file:
        filename = custom_file
    elif agent:
        filename = _AGENT_FILENAMES.get(agent, _AGENT_GENERIC_FILE)
    else:
        filename = None

    if agent == "cursor":
        content = _cursor_mdc(content)

    # --- Print mode ---
    if print_only:
        print(content)
        if filename:
            print(f"  # To write this to {filename}: cartograph setup" +
                  (f" --agent {agent}" if agent else "") +
                  (f" --file {custom_file}" if custom_file else ""))
        return

    # --- Write mode (default) ---
    filepath = os.path.join(target_dir, filename)
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)

    marker = "## Cartograph"
    workflow_marker = "### Workflow"
    if os.path.exists(filepath):
        with open(filepath) as f:
            existing = f.read()
        if marker in existing:
            if getattr(args, "overwrite", False):
                # Preserve workflow: if the existing section had one and the
                # user didn't pass --workflow explicitly, default it in so we
                # don't silently strip their workflow on overwrite.
                if workflow_marker in existing and getattr(args, "workflow", None) is None:
                    content_with_workflow = (
                        _build_setup_instructions() + _render_commands_block()
                        + _resolve_workflow("default")
                    )
                    if agent == "cursor":
                        content_with_workflow = _cursor_mdc(content_with_workflow)
                    overwrite_content = content_with_workflow
                    workflow_note = " (kept existing ### Workflow)"
                else:
                    overwrite_content = content
                    workflow_note = ""
                new_file = _replace_cartograph_section(existing, overwrite_content)
                with open(filepath, "w") as f:
                    f.write(new_file)
                print(f"\n  Replaced ## Cartograph section in {filepath}{workflow_note}")
                return
            # Section exists - check if user is just adding workflow
            workflow_content = _resolve_workflow(getattr(args, "workflow", None))
            if workflow_content and workflow_marker not in existing:
                with open(filepath, "a") as f:
                    f.write("\n" + workflow_content)
                print(f"\n  Added workflow to existing Cartograph section in {filepath}")
                return
            print(f"\n  Cartograph section already exists in {filepath}")
            if workflow_marker in existing:
                print(f"  Workflow section is already included.")
            print(f"  Pass --overwrite to replace the existing section with a fresh one.\n")
            return

    with open(filepath, "a") as f:
        f.write("\n" + content)

    if detected_reason:
        print(f"\n  Detected {agent} (found {detected_reason})")
    print(f"  Appended to {filepath}")
    if not getattr(args, "workflow", None):
        print(f"  Tip: add --workflow to include suggested workflow guidelines")
    print()


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------

def cmd_registry(args):
    """Manage additional registries (config registry add/list/remove)."""
    action = getattr(args, "action", None)
    url = getattr(args, "url", None)
    prefix = getattr(args, "prefix", None)
    reg_prefix = getattr(args, "reg_prefix", None)

    if action == "add":
        if not url:
            err({"error": "URL required: cartograph registry add <url>"})
        from .config import add_registry
        result_prefix, error, needs_prefix = add_registry(url, prefix=prefix)
        if needs_prefix:
            print(f"\n  Warning: Could not fetch prefix from {url}:")
            print(f"    {error}")
            print(f"\n  Add it manually once you know the prefix:")
            print(f"    cartograph registry add {url} --prefix <name>\n")
            return
        if error:
            err({"error": error})
        print(f"\n  Registry added: {result_prefix} -> {url}\n")
        print(f"  Install widgets: cartograph install {result_prefix}-<widget-name>\n")

    elif action == "remove":
        # reg_prefix is the second positional (url slot) when action=remove
        target = reg_prefix or url
        if not target:
            err({"error": "Prefix required: cartograph registry remove <prefix>"})
        from .config import remove_registry
        error = remove_registry(target)
        reg_prefix = target
        if error:
            err({"error": error})
        print(f"\n  Registry '{reg_prefix}' removed.\n")

    else:
        # List
        from .config import get_registries, _PUBLIC_REGISTRY_URL, _PUBLIC_REGISTRY_PREFIX
        registries = get_registries()
        print()
        print(f"  {'PREFIX':<12}  URL")
        print(f"  {'-'*12}  {'-'*40}")
        print(f"  {_PUBLIC_REGISTRY_PREFIX:<12}  {_PUBLIC_REGISTRY_URL}  (public, always available)")
        for reg in registries:
            print(f"  {reg['prefix']:<12}  {reg['url']}")
        print()
        if registries:
            print(f"  Install: cartograph install <prefix>-<widget-name>")
        else:
            print(f"  Add a registry: cartograph registry add <url>")
        print()


def cmd_config(args):
    """View or change settings. No args = list all, key = get, key value = set.

    Default output is human-friendly aligned prose. Pass --json for structured
    output (used by the MCP config tool and anything else that needs to parse
    the result).
    """
    key = getattr(args, "key", None)
    value = getattr(args, "value", None)
    as_json = getattr(args, "as_json", False)

    if not key:
        from .config import list_values, visibility_has_effect
        items = list_values()
        vis_effective, active_registry = visibility_has_effect()
        if as_json:
            for item in items:
                if item["key"] == "visibility" and not vis_effective:
                    item["effective"] = False
                    item["note"] = (
                        f"No effect: publish-registry is '{active_registry}', "
                        f"which treats all widgets as public."
                    )
            out({"status": "success", "settings": items})
            return
        def _display_value(item):
            val = item["value"]
            # Empty string counts as unset for display purposes (happens when
            # a string key has never been set or was cleared via `config <k> ""`).
            if val is not None and val != "":
                return str(val)
            default = item.get("default")
            if default is not None and default != "":
                return f"{default} (default)"
            return "-"

        max_key = max((len(i["key"]) for i in items), default=0)
        max_val = max((len(_display_value(i)) for i in items), default=0)
        print()
        for item in items:
            choices = f"  {' | '.join(item['choices'])}" if item["choices"] else ""
            suffix = ""
            if item["key"] == "visibility" and not vis_effective:
                suffix = f"  (no effect on '{active_registry}' registry; all widgets public)"
            print(f"  {item['key']:<{max_key}}   {_display_value(item):<{max_val}}   {item['description']}{choices}{suffix}")
        print()
    elif value is None:
        from .config import get_value
        val, error = get_value(key)
        if error:
            err({"error": error})
        if as_json:
            out({"status": "success", "key": key, "value": val})
            return
        display = val if val is not None else "(not set)"
        print(f"\n  {key} = {display}\n")
    else:
        from .config import set_value, visibility_has_effect
        error = set_value(key, value)
        if error:
            err({"error": error})
        # `visibility` is a no-op while publish-registry is the public `cg`
        # community registry (everything is public there). Accept the set
        # either way so the preference is kept if the user later switches
        # to a self-hosted registry, but flag it loudly.
        warning = None
        if key == "visibility":
            vis_effective, active_registry = visibility_has_effect()
            if not vis_effective:
                warning = (
                    f"visibility is a no-op on the '{active_registry}' registry "
                    f"(all widgets are public there). This setting will take "
                    f"effect if you publish to a self-hosted registry."
                )
        if as_json:
            payload = {"status": "success", "key": key, "value": value}
            if warning:
                payload["warning"] = warning
            out(payload)
            return
        print(f"\n  Set {key} = {value}")
        if warning:
            print(f"  Note: {warning}")
        print()


# ---------------------------------------------------------------------------
# CLI definition (declarative via infra-agent-cli-python widget)
# ---------------------------------------------------------------------------

def _build_cli() -> AgentCLI:
    from . import __version__
    from .languages.registry import supported_languages

    cli = AgentCLI(
        prog="cartograph",
        description="Cartograph widget library manager",
        version=__version__,
        colors={
            "heading": "\033[33m",   # yellow (--accent #D4A017)
            "groups": [
                "\033[36m",  # cyan    - Use widgets
                "\033[32m",  # green   - Build widgets
                "\033[35m",  # magenta - Cloud registry
                "\033[34m",  # blue    - Config
            ],
        },
    )

    cli.add_commands("Use widgets", [
        {
            "name": "search",
            "help": "Search the widget library",
            "handler": cmd_search,
            "args": [
                {"name": "query", "help": "Search query"},
                {"name": "--domain", "default": None, "help": "Filter by domain"},
                {"name": "--language", "default": None, "help": "Filter by language"},
                {"name": "--top-k", "type": int, "default": 10, "dest": "top_k"},
            ],
        },
        {
            "name": "inspect",
            "help": "Show widget details",
            "handler": cmd_inspect,
            "args": [
                {"name": "widget_id"},
                {"name": "--source", "action": "store_true", "default": False, "help": "Include source files"},
                {"name": "--all-versions", "action": "store_true", "default": False, "dest": "all_versions"},
                {"name": "--reviews", "action": "store_true", "default": False},
                {"name": "--version", "default": None, "help": "Inspect a specific historical version"},
            ],
        },
        {
            "name": "install",
            "help": "Install a widget into your project",
            "handler": cmd_install,
            "args": [
                {"name": "widget_id"},
                {"name": "--target", "default": ".", "help": "Project root (default: .)"},
                {"name": "--version", "default": None},
            ],
        },
        {
            "name": "uninstall",
            "help": "Remove a widget from your project",
            "handler": cmd_uninstall,
            "args": [
                {"name": "widget_dir", "help": "Path to installed widget dir (e.g. cg/infra_foo_python)"},
            ],
        },
        {
            "name": "upgrade",
            "help": "Upgrade an installed widget to the latest version",
            "handler": cmd_upgrade,
            "args": [
                {"name": "widget_dir", "help": "Path to installed widget dir (e.g. cg/infra_foo_python)"},
                {"name": "--version", "default": None},
            ],
        },
        {
            "name": "status",
            "help": "Check installed widget(s) - omit widget_dir to scan all",
            "handler": cmd_status,
            "args": [
                {"name": "widget_dir", "nargs": "?", "default": None,
                 "help": "Path to installed widget dir, or omit to scan all"},
                {"name": "--page", "type": int, "default": 1,
                 "help": "1-indexed page for aggregate listing (default: 1)"},
                {"name": "--size", "type": int, "default": 20,
                 "help": "Page size for aggregate listing (default: 20, max: 500)"},
                {"name": "--all", "action": "store_true", "default": False, "dest": "all_widgets",
                 "help": "Return every widget (disables pagination). Mutually exclusive with --page/--size."},
            ],
        },
        {
            "name": "rate",
            "help": "Rate a widget (local dir path or @handle/widget-id for cloud)",
            "handler": cmd_rate,
            "args": [
                {"name": "widget_id", "help": "Widget dir path or @handle/widget-id for cloud"},
                {"name": "score", "type": float, "help": "Score from 1.0 to 5.0"},
                {"name": "--comment", "default": None},
            ],
        },
    ])

    cli.add_commands("Build widgets", [
        {
            "name": "create",
            "help": "Scaffold a new widget",
            "handler": cmd_create,
            "args": [
                {"name": "widget_id",
                 "help": "Widget slug (e.g. 'retry-backoff'). The --domain prefix and "
                         "--language suffix are added automatically, producing IDs like "
                         "'backend-retry-backoff-python'."},
                {"name": "--language", "required": True, "choices": supported_languages(),
                 "help": "Implementation language. Determines scaffold templates and validation engine."},
                {"name": "--domain", "required": True,
                 "choices": sorted(__import__('cartograph.validator', fromlist=['VALID_DOMAINS']).VALID_DOMAINS),
                 "help": "Widget domain. Becomes the prefix in the widget ID and influences scaffold notes."},
                {"name": "--name", "default": None,
                 "help": "Optional display name for widget.json (e.g. 'Retry with Backoff'). "
                         "Defaults to the title-cased slug."},
                {"name": "--target", "default": ".",
                 "help": "Project root to create the widget under (widget lands in <target>/cg/<widget_id>/). Default: ."},
            ],
        },
        {
            "name": "rename",
            "help": "Rename a scaffolded widget's slug or domain (pre-checkin, Python-only)",
            "handler": cmd_rename,
            "args": [
                {"name": "widget_id", "help": "Current widget ID (e.g. 'infra-urllib-client-python')"},
                {"name": "--name", "default": None,
                 "help": "New slug segment (e.g. 'http-client'). Just the middle part, not the full ID."},
                {"name": "--domain", "default": None,
                 "choices": sorted(__import__('cartograph.validator', fromlist=['VALID_DOMAINS']).VALID_DOMAINS),
                 "help": "New domain. Language is immutable; use create for a cross-language port."},
                {"name": "--target", "default": ".",
                 "help": "Project root; if the widget is installed here, renames its cg/ copy too. Default: ."},
            ],
        },
        {
            "name": "validate",
            "help": "Run the validation pipeline on a widget",
            "handler": cmd_validate,
            "args": [
                {"name": "path", "nargs": "?", "default": ".", "help": "Widget directory or widget_id with --lib"},
                {"name": "--lib", "action": "store_true", "default": False, "help": "Treat path as a library widget_id"},
            ],
        },
        {
            "name": "checkin",
            "help": "Check a widget into the library (--publish to also publish)",
            "handler": cmd_checkin,
            "args": [
                {"name": "path", "nargs": "?", "default": ".", "help": "Widget directory (default: .)"},
                {"name": "--reason", "required": True, "help": "What changed and why"},
                {"name": "--bump", "default": "minor", "choices": ["major", "minor", "patch"],
                 "help": "Version bump type (default: minor)"},
                {"name": "--publish", "action": "store_true", "default": False,
                 "help": "Publish to cloud after checkin"},
                {"name": "--override-warnings", "action": "store_true", "default": False, "dest": "override_warnings"},
                {"name": "--override-reason", "default": None, "dest": "override_reason"},
            ],
        },
        {
            "name": "rollback",
            "help": "Roll back a widget to a previous version (local + cloud)",
            "handler": cmd_rollback,
            "args": [
                {"name": "widget_id", "help": "Widget ID (local) or @handle/widget_id (cloud)"},
                {"name": "--version", "default": None, "help": "Version to roll back to (omit to list)"},
                {"name": "--reason", "default": "", "help": "Reason for rollback"},
            ],
        },
        {
            "name": "delete",
            "help": "Remove a widget from the library (and cloud if published)",
            "handler": cmd_delete,
            "args": [
                {"name": "widget_id"},
                {"name": "--confirm", "action": "store_true", "default": False,
                 "help": "Actually delete (irreversible)"},
            ],
        },
    ])

    cli.add_commands("Cloud registry", [
        {
            "name": "cloud publish",
            "help": "Publish a widget to the cloud registry",
            "handler": cmd_cloud_publish,
            "args": [
                {"name": "widget_id", "nargs": "?", "default": None,
                 "help": "Widget ID (required with --lib, inferred otherwise)"},
                {"name": "path", "nargs": "?", "default": ".", "help": "Widget directory (default: .)"},
                {"name": "--lib", "action": "store_true", "default": False},
                {"name": "--visibility", "default": None, "choices": ["public", "private"],
                 "help": "Override default visibility"},
                {"name": "--governance", "default": None, "choices": ["open", "protected"],
                 "help": "Override default governance model"},
                {"name": "--override-warnings", "action": "store_true", "default": False, "dest": "override_warnings"},
                {"name": "--override-reason", "default": None, "dest": "override_reason"},
            ],
        },
        {
            "name": "cloud adopt",
            "help": "Link a local widget to its cloud counterpart",
            "description": (
                "Verifies that a local library widget and a cloud widget have identical\n"
                "source files, then writes a .cartograph_source sidecar so future\n"
                "checkin --publish routes to the correct registry and owner.\n\n"
                "Useful when migrating an existing project to multi-registry, or when\n"
                "a widget was created locally and published separately.\n\n"
                "Example: cartograph cloud adopt backend-retry-python @benteigland11/cg-backend-retry-python"
            ),
            "handler": cmd_cloud_adopt,
            "args": [
                {"name": "local_id", "help": "Local library widget id (e.g. backend-retry-python)"},
                {"name": "cloud_id", "help": "Cloud widget reference (e.g. @owner/cg-widget-name)"},
                {"name": "--force", "action": "store_true", "default": False,
                 "help": "Overwrite existing sidecar if present"},
            ],
        },
        {
            "name": "cloud unpublish",
            "help": "Remove a widget from the cloud (keeps local)",
            "handler": cmd_cloud_unpublish,
            "args": [
                {"name": "widget_id"},
                {"name": "--confirm", "action": "store_true", "default": False, "help": "Required to proceed"},
            ],
        },
        {
            "name": "cloud settings",
            "help": "View or change a cloud widget's settings",
            "handler": cmd_cloud_settings,
            "args": [
                {"name": "widget_id", "help": "Widget ID (@handle/widget-id)"},
                {"name": "--governance", "default": None, "choices": ["open", "protected"],
                 "help": "Set governance model"},
                {"name": "--visibility", "default": None, "choices": ["public", "private"],
                 "help": "Set visibility"},
            ],
        },
        {
            "name": "cloud sync",
            "help": "Sync library with cloud (higher version wins, both directions)",
            "handler": cmd_sync,
            "args": [
                {"name": "--dry-run", "action": "store_true", "default": False, "dest": "dry_run"},
            ],
        },
        {
            "name": "cloud proposals",
            "help": "List, accept, or reject proposals",
            "handler": cmd_cloud_proposals,
            "args": [
                {"name": "widget_id", "nargs": "?", "default": None,
                 "help": "Widget ID (@owner/widget-id) - required for accept/reject"},
                {"name": "proposal_id", "nargs": "?", "default": None,
                 "help": "Proposal ID to view/act on"},
                {"name": "--accept", "action": "store_true", "default": False,
                 "help": "Accept the proposal"},
                {"name": "--reject", "action": "store_true", "default": False,
                 "help": "Reject the proposal"},
                {"name": "--reason", "default": "", "help": "Reason for rejection"},
                {"name": "--diff", "action": "store_true", "default": False,
                 "help": "Fetch and print the unified diff for a proposal"},
            ],
        },
    ])

    cli.add_commands("Config", [
        {
            "name": "registry",
            "help": "Manage additional widget registries",
            "description": (
                "Add, list, or remove company/private registries alongside the public one.\n\n"
                "The public Cartograph registry (prefix: cg) is always available.\n"
                "Company registries register their own prefix via a /info endpoint.\n\n"
                "Actions:\n"
                "  (none)   List all configured registries\n"
                "  add      Add a registry: cartograph registry add <url>\n"
                "           Fetches prefix automatically from the registry's /info endpoint.\n"
                "           Override with --prefix if the registry doesn't expose /info.\n"
                "  remove   Remove a registry: cartograph registry remove <prefix>"
            ),
            "handler": cmd_registry,
            "args": [
                {"name": "action", "nargs": "?", "default": None,
                 "help": "add | remove (omit to list)"},
                {"name": "url", "nargs": "?", "default": None,
                 "help": "Registry URL (for add)"},
                {"name": "--prefix", "default": None,
                 "help": "Override prefix (if registry does not expose /info)"},
                {"name": "reg_prefix", "nargs": "?", "default": None,
                 "help": "Registry prefix to remove (for remove)"},
            ],
        },
        {
            "name": "config",
            "help": "View or change settings (config [key] [value])",
            "handler": cmd_config,
            "args": [
                {"name": "key", "nargs": "?", "default": None,
                 "help": "Setting name (e.g. auto-publish)"},
                {"name": "value", "nargs": "?", "default": None,
                 "help": "Value to set (omit to read)"},
                {"name": "--json", "action": "store_true", "default": False,
                 "dest": "as_json", "help": "Emit JSON for machine consumption (used by the MCP layer)"},
            ],
        },
        {
            "name": "rules",
            "help": "List and manage custom validation rules",
            "description": (
                "Custom rules are scripts that run automatically during `cartograph validate`\n"
                "and `cartograph checkin`. They let you enforce team conventions on top of\n"
                "Cartograph's built-in quality bar (coverage, contamination, etc).\n\n"
                "Global rules apply to all projects on this machine and are created\n"
                "automatically at first run - just open the file and add checks.\n\n"
                "Project rules live in .cartograph/rules/ and are checked into your repo,\n"
                "so they apply to everyone who uses the project. Create them with:\n"
                "  cartograph rules init --language python\n\n"
                "Actions:\n"
                "  (none)   List all active rules files with their paths\n"
                "  init     Create a project-level rules file from a template\n"
                "  reset    Restore a rules file to its default template (clears edits, requires --confirm)"
            ),
            "handler": cmd_rules,
            "args": [
                {"name": "action", "nargs": "?", "default": None,
                 "help": "init | get | write | reset (omit to list)"},
                {"name": "--language", "default": None,
                 "help": "Language for the rules file (e.g. python, javascript, css)"},
                {"name": "--global", "action": "store_const", "const": "global",
                 "default": "project", "dest": "scope",
                 "help": "Target the global rules file instead of the project one"},
                {"name": "--confirm", "action": "store_true", "default": False,
                 "help": "Confirm overwrite (required for reset, and for write when a rules file already exists)"},
                {"name": "--content", "default": None,
                 "help": "Rules content for 'write' action (string). Use --from-file or stdin for longer payloads."},
                {"name": "--from-file", "default": None, "dest": "from_file",
                 "help": "Read 'write' content from a file path instead of --content."},
                {"name": "--json", "action": "store_true", "default": False,
                 "dest": "as_json",
                 "help": "Emit JSON for machine consumption (used by the MCP layer)."},
            ],
        },
        {
            "name": "workflow",
            "help": "List, view, or create workflows",
            "handler": cmd_workflow,
            "args": [
                {"name": "name", "nargs": "?", "default": None,
                 "help": "Workflow name (or 'create')"},
                {"name": "source", "nargs": "?", "default": None,
                 "help": "For create: workflow name. For view: unused"},
                {"name": "extra", "nargs": "?", "default": None,
                 "help": "For create: source .md file path"},
            ],
        },
        {
            "name": "setup",
            "help": "Set up Cartograph for your AI agent (auto-detects and appends)",
            "handler": cmd_setup,
            "args": [
                {"name": "--agent", "default": None,
                 "choices": ["claude", "codex", "gemini", "antigravity", "cursor"],
                 "help": "Agent to configure (auto-detected if omitted)"},
                {"name": "--file", "default": None,
                 "help": "Write to a custom file instead of the agent default"},
                {"name": "--print", "action": "store_true", "default": False,
                 "help": "Print instructions to stdout instead of writing"},
                {"name": "--workflow", "nargs": "?", "default": None, "const": "default",
                 "help": "Include workflow (default or custom name from workflows/)"},
                {"name": "--overwrite", "action": "store_true", "default": False,
                 "help": "Replace the existing ## Cartograph section in place (preserves everything else in the file)"},
            ],
        },
        {
            "name": "login",
            "help": "Authenticate with the Cartograph cloud registry",
            "handler": cmd_login,
            "args": [
                {"name": "--token", "default": None, "help": "API token"},
                {"name": "--registry", "default": None,
                 "help": "Store an access token for a private registry (e.g. --registry myorg --token <key>). Does not change your publish identity."},
            ],
        },
        {
            "name": "logout",
            "help": "Remove stored cloud credentials",
            "handler": cmd_logout,
            "args": [],
        },
        {
            "name": "whoami",
            "help": "Show current authenticated user",
            "handler": cmd_whoami,
            "args": [],
        },
        {
            "name": "dashboard",
            "help": "Open local widget dashboard in browser",
            "handler": cmd_dashboard,
            "args": [
                {"name": "--port", "type": int, "default": 0, "help": "Override port"},
                {"name": "--set-port", "type": int, "default": None, "dest": "set_port"},
                {"name": "--stop", "action": "store_true", "default": False},
            ],
        },
        {
            "name": "export",
            "help": "Export widget library as a zip file",
            "handler": cmd_export,
            "args": [
                {"name": "--output", "default": None,
                 "help": "Output file (default: cartograph-library.zip)"},
            ],
        },
        {
            "name": "import",
            "help": "Import widgets from a zip file into the library",
            "handler": cmd_import,
            "args": [
                {"name": "path", "help": "Path to zip file"},
                {"name": "--force", "action": "store_true", "default": False,
                 "help": "Overwrite existing files"},
            ],
        },
        {
            "name": "stats",
            "help": "Show library statistics",
            "handler": cmd_stats,
            "args": [],
        },
        {
            "name": "doctor",
            "help": "Check language engine dependencies",
            "handler": cmd_doctor,
            "args": [],
        },
    ])

    return cli


def build_parser():
    """Build argparse parser (for backward compat with tests)."""
    return _build_cli().build_parser()


def _force_utf8_io():
    """Force stdout/stderr to UTF-8 on Windows.

    Windows Python defaults stdout to the legacy console code page
    (cp1252), which crashes with UnicodeEncodeError the first time we
    print a box-drawing char, check mark, or arrow - every `doctor`
    run, every progress line. Users can work around it with PYTHONUTF8=1
    but most don't know that and we control the entry point.

    Wrapped streams (pytest capsys, redirected pipes) may not expose
    `reconfigure`; in that case there's nothing to fix and we leave
    them as-is.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _force_utf8_io()
    from .update_check import maybe_recommend_update
    maybe_recommend_update()
    _build_cli().run()


if __name__ == "__main__":
    main()
