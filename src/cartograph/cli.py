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

from cg.infra_agent_cli_python.src.agent_cli import AgentCLI, out, err


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
    try:
        from .cloud import whoami as _whoami
        _profile = _whoami()
        _me = _profile.get("owner", "") or _profile.get("username", "")
    except Exception:
        _me = ""

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
        print(f"\n  No widgets found for '{args.query}'.")
        if args.domain or args.language:
            print("  Try broadening your search by removing --domain or --language filters.")
        print("  Run 'cartograph doctor' to check available language engines.\n")
        return

    out(merged)


def cmd_inspect(args):
    widget_id = args.widget_id

    # Cloud widget: @handle/widget_id
    if widget_id.startswith("@"):
        parts = widget_id[1:].split("/", 1)
        if len(parts) != 2:
            err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner, wid = parts
        from .cloud import inspect as cloud_inspect
        result = cloud_inspect(owner, wid, source=args.source)
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
        print("    Note: Code is validated locally by the uploader. Review before use.")


def cmd_install(args):
    result = _carto().install(
        widget_id=args.widget_id,
        target_dir=os.path.abspath(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        err(result)
    out(result)
    _cloud_install_note(result)


def cmd_uninstall(args):
    result = _carto().uninstall(
        widget_id=args.widget_id,
        target_dir=os.path.abspath(args.target),
    )
    if result.get("status") == "error":
        err(result)
    out(result)


def cmd_upgrade(args):
    result = _carto().upgrade(
        widget_id=args.widget_id,
        target_dir=os.path.abspath(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        err(result)
    out(result)
    _cloud_install_note(result)


def cmd_delete(args):
    result = _carto().delete(
        widget_id=args.widget_id,
        confirm=args.confirm,
    )
    if result.get("status") == "error":
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
    result = _carto().create(
        item_id=args.widget_id,
        language=args.language,
        domain=args.domain,
        name=args.name,
        target_dir=os.path.abspath(args.target),
    )
    if result.get("status") == "error":
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


def cmd_validate(args):
    path = _resolve_widget_path(args)
    _preflight_from_path(path)
    result = _carto().validate_item(path=path)
    if result.get("status") == "error":
        err(result)
    if result.get("warnings"):
        import sys as _sys
        print("\nWarnings:", file=_sys.stderr)
        for w in result["warnings"]:
            print(f"  {w}", file=_sys.stderr)
        print("", file=_sys.stderr)
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


def _resolve_publish_registry(install_path: str) -> str | None:
    """Return the registry URL to publish to, given the widget's install path.

    Derives registry from the install dir's prefix (e.g. cg/myorg-widget/ → myorg
    registry URL). Falls back to the 'publish-registry' config key, then public.
    Returns None to indicate public registry (default).
    """
    from .config import get_registries, get_registry_url_for_prefix, get_value, _PUBLIC_REGISTRY_PREFIX

    dir_name = os.path.basename(install_path.rstrip(os.sep)).replace("_", "-")
    for reg in get_registries():
        prefix = reg["prefix"]
        if dir_name.startswith(prefix + "-"):
            return reg["url"]
    if dir_name.startswith(_PUBLIC_REGISTRY_PREFIX + "-"):
        return None  # public registry, no override needed

    # No prefix in dir name - check publish-registry config
    configured_prefix, _ = get_value("publish-registry")
    if configured_prefix:
        return get_registry_url_for_prefix(configured_prefix)

    return None  # default: public registry


def _force_push(checkin_result: dict, install_path: str | None = None,
                reason: str = "") -> None:
    """Push to cloud, or propose to origin owner if widget was installed from someone else."""
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
            print(f"  → Widget installed from @{origin_owner} - submitting as proposal...")
            propose_result = cloud.propose(widget_path, origin_owner, widget_id,
                                           reason=reason or "Improvement proposal",
                                           registry_url=origin_registry)
            if propose_result.get("error"):
                print(f"  → Proposal failed: {propose_result['error']}")
            else:
                status = propose_result.get("status", "proposed")
                print(f"  → Proposal {status}: {propose_result.get('proposal_id', '')}")
            return

    registry_url = _resolve_publish_registry(install_path) if install_path else None
    cfg = load_config()
    visibility = cfg["publish"]["visibility"]
    governance = cfg["publish"].get("governance")
    print(f"  → Pushing {widget_id} v{checkin_result.get('version', '?')} to cloud...")
    push_result = cloud.push(widget_path, widget_id, visibility=visibility,
                             governance=governance, registry_url=registry_url)
    if push_result.get("error"):
        print(f"  → Push failed: {push_result['error']}")
    else:
        print(f"  → Pushed: {push_result.get('namespaced_id', widget_id)} v{push_result.get('version', '?')}")


def _auto_push_if_published(checkin_result: dict, install_path: str | None = None) -> None:
    """After a successful checkin update, auto-push if the widget exists on the cloud."""
    from . import cloud, auth
    if not auth.is_authenticated() or not cloud.is_available():
        return
    widget_id = checkin_result.get("id", "")
    widget_path = checkin_result.get("path", "")
    if not widget_id or not widget_path:
        return
    registry_url = _resolve_publish_registry(install_path) if install_path else None
    profile = cloud.whoami()
    handle = profile.get("owner", "")
    if not handle:
        print("  → Auto-push skipped: could not resolve cloud owner.")
        return
    remote = cloud.inspect(handle, widget_id)
    if remote.get("error"):
        return  # not published — nothing to sync, this is the normal case
    print(f"  → Widget exists on cloud (v{remote.get('version', '?')}), pushing v{checkin_result.get('version', '?')}...")
    push_result = cloud.push(widget_path, widget_id, registry_url=registry_url)
    if push_result.get("error"):
        print(f"  → Auto-push failed: {push_result['error']}")
    else:
        print(f"  → Pushed to cloud: {push_result.get('namespaced_id', widget_id)} v{push_result.get('version', '?')}")


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
    if result.get("status") == "error":
        err(result)
    out(result)

    # Push to cloud: always if --publish or auto_publish config, otherwise only if already published
    if result.get("action") in ("updated", "registered"):
        from .config import load_config
        cfg = load_config()
        publish = getattr(args, "publish", False) or cfg["publish"]["auto_publish"]
        if publish:
            _force_push(result, install_path=install_path, reason=args.reason)
        else:
            _auto_push_if_published(result, install_path=install_path)


def cmd_status(args):
    target = os.path.abspath(args.target)

    if args.widget_id:
        result = _carto().widget_status(widget_id=args.widget_id, target_dir=target)
        if result.get("error"):
            err(result)
        out(result)
        return

    # No widget_id — scan all installed widgets
    from .engine import DEFAULT_INSTALL_DIR
    install_dir = os.path.join(target, DEFAULT_INSTALL_DIR)
    if not os.path.isdir(install_dir):
        print(f"\n  No widgets installed at {target}.")
        print(f"  Run 'cartograph install <widget_id>' to install one.\n")
        return

    widget_ids = [
        d for d in os.listdir(install_dir)
        if os.path.isfile(os.path.join(install_dir, d, "widget.json"))
    ]

    if not widget_ids:
        print(f"\n  No widgets installed at {target}.")
        print(f"  Run 'cartograph install <widget_id>' to install one.\n")
        return

    from .engine import normalize_widget_id
    carto = _carto()
    widgets = []
    for wid in sorted(widget_ids):
        r = carto.widget_status(widget_id=normalize_widget_id(wid), target_dir=target)
        widgets.append(r)

    out({
        "installed": len(widgets),
        "outdated": sum(1 for w in widgets if w.get("outdated")),
        "modified": sum(1 for w in widgets if w.get("modified")),
        "widgets": widgets,
    })


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
    result = push(path, widget_id, visibility=visibility, governance=governance)
    if "error" in result:
        err(result)

    nid      = result.get("namespaced_id", widget_id)
    version  = result.get("version", "?")
    vis      = result.get("visibility", "public")
    vis_icon = "🔒" if vis == "private" else "🌐"
    print(f"\n  ✓ Published {nid}  ·  v{version}  ·  {vis_icon} {vis}\n")


def cmd_rate(args):
    widget_id = args.widget_id

    # Cloud widget (@handle/widget_id)
    if widget_id.startswith("@"):
        from . import cloud, auth
        if not auth.is_authenticated():
            err({"error": "Not authenticated. Run: cartograph login"})
        parts = widget_id[1:].split("/", 1)
        if len(parts) != 2:
            err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner, wid = parts
        result = cloud.rate_widget(owner, wid, args.score, args.comment)
        if "error" in result:
            err(result)
        print(f"\n  Rated {widget_id}: {args.score}/5\n")
        return

    # Local widget
    result = _carto().add_review(
        widget_id=widget_id,
        target_dir=os.path.abspath(args.target),
        score=args.score,
        comment=args.comment,
    )
    if result.get("error"):
        err(result)
    out(result)


def cmd_cloud_unpublish(args):
    """Remove a widget from the cloud registry (keeps local copy)."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})
    if not getattr(args, "confirm", False):
        err({"error": f"This will remove '{args.widget_id}' from the cloud registry. Pass --confirm to proceed."})
    result = cloud.delete_widget(args.widget_id)
    if "error" in result:
        err(result)
    print(f"\n  Unpublished {args.widget_id} from cloud. Local copy unchanged.\n")



def cmd_rollback(args):
    """Roll back a widget to a previous version (local and/or cloud)."""
    from . import cloud, auth
    from .checkin import restore

    widget_id = args.widget_id
    version = args.version

    # Determine if this is a cloud widget (@handle/id) or local
    owner_handle = None
    base_id = widget_id
    if widget_id.startswith("@"):
        parts = widget_id[1:].split("/", 1)
        if len(parts) != 2:
            err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner_handle, base_id = parts

    carto = _carto()

    # If no version specified, list available versions
    if not version:
        if owner_handle:
            # Cloud: list versions from GCS
            result = cloud.get_versions(owner_handle, base_id)
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
        if result.get("status") == "error":
            print(f"  Local rollback failed: {result.get('message', 'unknown error')}")
        else:
            rolled_local = True
            new_version = result.get("version", "?")
            print(f"  ✓ Local: rolled back to v{version} (now v{new_version})")

    # Cloud rollback (if @handle/id or widget is published)
    if owner_handle:
        result = cloud.rollback_widget(owner_handle, base_id, version)
        if "error" in result:
            print(f"  Cloud rollback failed: {result.get('error', 'unknown error')}")
        else:
            rolled_cloud = True
            nv = result.get('new_version', '?')
            print(f"  ✓ Cloud: restored v{version} as v{nv} (was v{result.get('previous_version', '?')})")
    elif auth.is_authenticated():
        # Check if widget exists on cloud
        info = cloud.inspect(cloud.whoami().get("owner", ""), base_id)
        if "error" not in info:
            owner = info.get("owner", "")
            result = cloud.rollback_widget(owner, base_id, version)
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

    owner, wid = _parse_cloud_id(args.widget_id)

    visibility = getattr(args, "visibility", None)
    governance = getattr(args, "governance", None)

    # If no flags, show current settings
    if not governance and not visibility:
        result = cloud.inspect(owner, wid)
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

    result = cloud.update_widget(owner, wid, **kwargs)
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
            print(f"  [{status}]  @{owner}/{widget}  #{pid}")
        print(f"\n  Use --accept <id> or --reject <id> to act on a proposal.\n")
        return

    # Accept or reject
    owner, wid = _parse_cloud_id(args.widget_id)
    if getattr(args, "accept", False):
        result = cloud.accept_proposal(owner, wid, proposal_id)
        if "error" in result:
            err(result)
        print(f"\n  Proposal #{proposal_id} accepted.\n")
    elif getattr(args, "reject", False):
        reason = getattr(args, "reason", "")
        result = cloud.reject_proposal(owner, wid, proposal_id, reason=reason)
        if "error" in result:
            err(result)
        print(f"\n  Proposal #{proposal_id} rejected.\n")
    else:
        # Just viewing a specific proposal
        result = cloud.list_proposals(owner, wid)
        if "error" in result:
            err(result)
        proposals = result.get("proposals", [])
        match = next((p for p in proposals if str(p.get("id")) == str(proposal_id)), None)
        if not match:
            err({"error": f"Proposal #{proposal_id} not found."})
        out(match)


def cmd_rules(args):
    """List or initialize custom validation rules."""
    action = getattr(args, "action", None)

    if action == "reset":
        language = getattr(args, "language", None)
        scope = getattr(args, "scope", "project")

        if not language:
            err({"error": "Usage: cartograph rules reset --language python [--global]"})

        from .rules import get_template, get_rules_filename
        filename = get_rules_filename(language)
        if not filename:
            err({"error": f"No rules support for language '{language}'"})

        if scope == "global":
            from .engine import _user_data_dir
            rules_dir = os.path.join(_user_data_dir(), "rules")
        else:
            rules_dir = os.path.join(os.getcwd(), ".cartograph", "rules")

        filepath = os.path.join(rules_dir, filename)
        if not os.path.exists(filepath):
            print(f"\n  No rules file at {filepath}. Use `cartograph rules init` to create one.\n")
            return

        confirm = getattr(args, "confirm", False)
        if not confirm:
            print(f"\n  This will overwrite your custom rules at:")
            print(f"    {filepath}")
            print(f"\n  Re-run with --confirm to proceed.\n")
            return

        template = get_template(language)
        with open(filepath, "w") as f:
            f.write(template)

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

        if scope == "global":
            from .engine import _user_data_dir
            rules_dir = os.path.join(_user_data_dir(), "rules")
        else:
            rules_dir = os.path.join(os.getcwd(), ".cartograph", "rules")

        os.makedirs(rules_dir, exist_ok=True)
        filepath = os.path.join(rules_dir, filename)

        if os.path.exists(filepath):
            print(f"\n  Rules file already exists: {filepath}")
            print(f"  Open it in your editor to add or modify checks.\n")
            return

        with open(filepath, "w") as f:
            f.write(template)

        print(f"\n  Created: {filepath}")
        print(f"  Open it in your editor and uncomment or add checks.")
        print(f"  It runs automatically during `cartograph validate`.\n")
        return

    # Default: list rules files
    from .rules import find_rules

    rules = find_rules()
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


_SETUP_INSTRUCTIONS_TAIL = """\

### Commands

All commands run from your project root. Widgets install to `cg/` in the
current directory (or the directory specified by `--target`).

**Find and use widgets**

    search <query> [--domain ...] [--language ...]
      Search for widgets matching a query.

    inspect <widget_id> [--source] [--reviews] [--version X]
      View a widget's metadata, source code, or reviews.

    install <widget_id> [--target .] [--version X]
      Install a widget into your project.

    uninstall <widget_id> [--target .]
      Remove an installed widget from your project.

    upgrade <widget_id> [--target .] [--version X]
      Update an installed widget to the latest version.

    status [widget_id] [--target .]
      Check if an installed widget is outdated or locally modified.

    rate <widget_id> <score 1-5> [--comment "..."]
      Rate an installed widget (1-5). Ratings affect search ranking.

**Create and publish widgets**

    create <widget_id> --language <lang> --domain <domain>
      Scaffold a new widget with the correct directory structure.

    validate [path] [--lib]
      Run tests, check for contamination, and verify widget correctness.

    checkin [path] --reason "..." [--bump patch|minor|major] [--publish]
      Push an edited widget back to the library. Runs validation if needed.

    rollback <widget_id> [--version X] [--reason "..."]
      Restore a previous version of a widget from history.

    delete <widget_id> [--confirm]
      Remove a widget from the library and cloud.

**Cloud registry**

    cloud publish [widget_id] [path] [--visibility ...] [--governance ...]
      Publish a widget to the cloud registry.

    cloud unpublish <widget_id> [--confirm]
      Remove a widget from the cloud registry.

    cloud sync [--dry-run]
      Sync local library with cloud. Higher version wins.

    cloud proposals [widget_id] [--accept] [--reject] [--reason "..."]
      Review community-submitted changes to your published widgets.

**Custom validation rules**

    rules
      List all active rules files.

    rules init --language <lang> [--global]
      Create a rules file from a template. Edit it in your editor to add
      checks. Runs automatically during `cartograph validate`.
      Per-project: .cartograph/rules/   Global: <data_dir>/rules/

    rules reset --language <lang> [--global]
      Restore a rules file to its default template.

**Configuration**

    config [key] [value]
      View or change settings.

    setup [--agent ...] [--file X] [--print] [--workflow]
      Write Cartograph instructions to your agent's config file.
      Auto-detects agent. Appends, never replaces.

    doctor
      Check system health - library, languages, cloud connectivity.

    stats
      Show library statistics.
"""

_WORKFLOW_SECTION = """
### Workflow

Think in terms of widgets. Need to add capability, search for a widget.

If you are adding a feature always consider whether it can be added into an existing widget. If not, consider if it could be added as a new widget.
Only project specific wiring should not be made into widgets.

1. Plan what components you need before building
2. Search the library before writing new logic
3. Install widgets, then write glue code to connect them. Don't edit widget source directly for this step.
4. If you do edit a widget, only do so if you intend to check it back in as an improvement for the general logic of the widget.
5. Validate before checking in, check in before publishing
"""

_AGENT_FILENAMES = {
    "claude":       "CLAUDE.md",
    "codex":        "AGENTS.md",
    "gemini":       "GEMINI.md",
    "antigravity":  "GEMINI.md",
    "cursor":       os.path.join(".cursor", "rules", "cartograph.mdc"),
}

_AGENT_GENERIC_FILE = "AGENT.md"


def _detect_agent(directory: str) -> tuple[str | None, str | None]:
    """Auto-detect which AI agent is in use from project files.

    Returns (agent_name, reason) or (None, None) if nothing detected.
    Detection order matters - first match wins.
    """
    if os.path.isdir(os.path.join(directory, ".claude")):
        return "claude", ".claude/ directory"
    if os.path.isfile(os.path.join(directory, "CLAUDE.md")):
        return "claude", "CLAUDE.md"
    if os.path.isdir(os.path.join(directory, ".cursor")):
        return "cursor", ".cursor/ directory"
    if os.path.isfile(os.path.join(directory, "AGENTS.md")):
        return "codex", "AGENTS.md"
    if os.path.isfile(os.path.join(directory, "GEMINI.md")):
        return "gemini", "GEMINI.md"
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
        print("\n  Library is empty.\n")
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
            rated.append((w["name"], w["rating"]))
        if w.get("install_count", 0):
            installed.append((w["name"], w["install_count"]))

    rated.sort(key=lambda x: x[1], reverse=True)
    installed.sort(key=lambda x: x[1], reverse=True)

    all_ratings = [w.get("rating", 0) for w in widgets if w.get("rating", 0)]
    avg_rating  = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0
    total_installs = sum(w.get("install_count", 0) for w in widgets)

    print()
    print(f"  Library  {len(widgets)} widgets  |  {total_installs} total installs  |  avg rating {avg_rating}/5.0")
    print()

    print("  By language")
    for lang, count in sorted(by_language.items()):
        print(f"    {lang:<16}  {count}")
    print()

    print("  By domain")
    for domain, count in sorted(by_domain.items()):
        print(f"    {domain:<16}  {count}")
    print()

    if installed:
        print("  Most installed")
        for name, count in installed[:5]:
            print(f"    {name:<32}  {count} installs")
        print()

    if rated:
        print("  Top rated")
        for name, rating in rated[:5]:
            print(f"    {name:<32}  {rating}/5.0")
        print()


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
            print(f"  Or create a generic AGENT.md:")
            print(f"    cartograph setup --file AGENT.md")
            print()
            return

    # --- Build content ---
    content = _build_setup_instructions() + "\n" + _SETUP_INSTRUCTIONS_TAIL
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
            print(f"  Remove the existing ## Cartograph section and re-run to replace it.\n")
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
    """View or change settings. No args = list all, key = get, key value = set."""
    key = getattr(args, "key", None)
    value = getattr(args, "value", None)

    if not key:
        # List all
        from .config import list_values
        items = list_values()
        max_key = max((len(i["key"]) for i in items), default=0)
        max_val = max((len(str(i["value"] if i["value"] is not None else "-")) for i in items), default=0)
        print()
        for item in items:
            val = item["value"]
            display = str(val) if val is not None else "-"
            choices = f"  {' | '.join(item['choices'])}" if item["choices"] else ""
            print(f"  {item['key']:<{max_key}}   {display:<{max_val}}   {item['description']}{choices}")
        print()
    elif value is None:
        # Get
        from .config import get_value
        val, error = get_value(key)
        if error:
            err({"error": error})
        display = val if val is not None else "(not set)"
        print(f"\n  {key} = {display}\n")
    else:
        # Set
        from .config import set_value
        error = set_value(key, value)
        if error:
            err({"error": error})
        print(f"\n  Set {key} = {value}\n")


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
                {"name": "widget_id"},
                {"name": "--target", "default": ".", "help": "Project root (default: .)"},
            ],
        },
        {
            "name": "upgrade",
            "help": "Upgrade an installed widget to the latest version",
            "handler": cmd_upgrade,
            "args": [
                {"name": "widget_id"},
                {"name": "--target", "default": ".", "help": "Project root (default: .)"},
                {"name": "--version", "default": None},
            ],
        },
        {
            "name": "status",
            "help": "Check installed widget(s) - omit widget_id to scan all",
            "handler": cmd_status,
            "args": [
                {"name": "widget_id", "nargs": "?", "default": None},
                {"name": "--target", "default": ".", "help": "Project root (default: .)"},
            ],
        },
        {
            "name": "rate",
            "help": "Rate a widget (local or @handle/widget-id for cloud)",
            "handler": cmd_rate,
            "args": [
                {"name": "widget_id", "help": "Widget ID or @handle/widget-id"},
                {"name": "score", "type": float, "help": "Score from 1.0 to 5.0"},
                {"name": "--comment", "default": None},
                {"name": "--target", "default": ".", "help": "Project root (default: .)"},
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
                 "help": "init | reset (omit to list)"},
                {"name": "--language", "default": None,
                 "help": "Language for the rules file (e.g. python, javascript, css)"},
                {"name": "--global", "action": "store_const", "const": "global",
                 "default": "project", "dest": "scope",
                 "help": "Target the global rules file instead of the project one"},
                {"name": "--confirm", "action": "store_true", "default": False,
                 "help": "Confirm reset (required - reset overwrites your edits)"},
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
            ],
        },
        {
            "name": "login",
            "help": "Authenticate with the Cartograph cloud registry",
            "handler": cmd_login,
            "args": [
                {"name": "--token", "default": None, "help": "API token"},
                {"name": "--registry", "default": None,
                 "help": "Registry prefix for company registry login (requires --token)"},
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


def main():
    _build_cli().run()


if __name__ == "__main__":
    main()
