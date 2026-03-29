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
except ImportError:
    # Fallback for pip installs where cg/ isn't available
    from cartograph._vendor.agent_cli import AgentCLI, out, err


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


def _resolve(path: str) -> str:
    return os.path.abspath(path)


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
    from .engine import DEFAULT_INSTALL_DIR
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
    try:
        with open(os.path.join(path, "widget.json")) as f:
            language = json.load(f).get("tech_stack", {}).get("language", "python")
        _preflight_language(language)
    except Exception:
        pass  # let the command itself report the missing file


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_search(args):
    local = _carto().search(
        query=args.query,
        domain_filter=args.domain,
        language_filter=args.language,
        top_k=args.top_k,
    )

    # Always search cloud — the registry is a public resource
    from .cloud import search as cloud_search
    cloud = cloud_search(
        query=args.query,
        domain_filter=args.domain,
        language_filter=args.language,
        top_k=args.top_k,
    )

    # Merge: cloud version wins for published widgets, local-only stays local.
    # Cloud results have id="@handle/widget_id", local have id="widget_id".
    # Deduplicate on base widget_id (strip @handle/ prefix).
    local_widgets = local.get("results", [])
    cloud_widgets = cloud.get("widgets", [])

    def _base_id(w):
        wid = w.get("id", "")
        return wid.split("/", 1)[1] if "/" in wid else wid

    cloud_base_ids = {_base_id(w) for w in cloud_widgets}

    seen = {}
    for w in cloud_widgets:
        seen[_base_id(w)] = w
    for w in local_widgets:
        bid = _base_id(w)
        if bid not in seen:
            seen[bid] = w

    combined = sorted(seen.values(), key=lambda w: w.get("relevance_score", 0), reverse=True)

    merged = {
        "local_count": sum(1 for w in combined if _base_id(w) not in cloud_base_ids),
        "cloud_count": sum(1 for w in combined if _base_id(w) in cloud_base_ids),
        "widgets": combined,
    }
    if cloud.get("error"):
        merged["cloud_error"] = cloud["error"]
    out(merged)


def cmd_inspect(args):
    result = _carto().inspect(
        widget_id=args.widget_id,
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
        target_dir=_resolve(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        err(result)
    out(result)
    _cloud_install_note(result)


def cmd_uninstall(args):
    result = _carto().uninstall(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
    )
    if result.get("status") == "error":
        err(result)
    out(result)


def cmd_upgrade(args):
    result = _carto().upgrade(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
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
        target_dir=_resolve(args.target),
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
    out(result)


def _force_push(checkin_result: dict) -> None:
    """Push to cloud regardless of whether the widget was previously published."""
    from . import cloud, auth
    if not auth.is_authenticated():
        print("  → Cannot push: not authenticated. Run: cartograph login", file=sys.stderr)
        return
    widget_id = checkin_result.get("id", "")
    widget_path = checkin_result.get("path", "")
    if not widget_id or not widget_path:
        return
    print(f"  → Pushing {widget_id} v{checkin_result.get('version', '?')} to cloud...")
    push_result = cloud.push(widget_path, widget_id)
    if push_result.get("error"):
        print(f"  → Push failed: {push_result['error']}")
    else:
        print(f"  → Pushed: {push_result.get('namespaced_id', widget_id)} v{push_result.get('version', '?')}")


def _auto_push_if_published(checkin_result: dict) -> None:
    """After a successful checkin update, auto-push if the widget exists on the cloud."""
    from . import cloud, auth
    if not auth.is_authenticated() or not cloud.is_available():
        return
    widget_id = checkin_result.get("id", "")
    widget_path = checkin_result.get("path", "")
    if not widget_id or not widget_path:
        return
    profile = cloud.whoami()
    handle = profile.get("owner", "")
    if not handle:
        return
    remote = cloud.inspect(handle, widget_id)
    if remote.get("error"):
        return  # not published — nothing to sync
    print(f"  → Widget exists on cloud (v{remote.get('version', '?')}), pushing v{checkin_result.get('version', '?')}...")
    push_result = cloud.push(widget_path, widget_id)
    if push_result.get("error"):
        print(f"  → Auto-push failed: {push_result['error']}")
    else:
        print(f"  → Pushed to cloud: {push_result.get('namespaced_id', widget_id)} v{push_result.get('version', '?')}")


def cmd_checkin(args):
    path = _resolve_widget(args.path)
    _preflight_from_path(path)
    result = _carto().checkin(
        path=path,
        reason=args.reason,
        version_bump=args.bump,
        override_warnings=args.override_warnings,
        override_reason=args.override_reason or "",
    )
    if result.get("status") == "error":
        err(result)
    out(result)

    # Push to cloud: always if --publish, otherwise only if already published
    if result.get("action") in ("updated", "registered"):
        if getattr(args, "publish", False):
            _force_push(result)
        else:
            _auto_push_if_published(result)


def cmd_status(args):
    target = _resolve(args.target)

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
        err({"error": f"No cartograph/ directory found at {target}"})

    widget_ids = [
        d for d in os.listdir(install_dir)
        if os.path.isfile(os.path.join(install_dir, d, "widget.json"))
    ]

    if not widget_ids:
        out({"installed": 0, "widgets": []})
        return

    carto = _carto()
    widgets = []
    for wid in sorted(widget_ids):
        r = carto.widget_status(widget_id=wid, target_dir=target)
        widgets.append(r)

    out({
        "installed": len(widgets),
        "outdated": sum(1 for w in widgets if w.get("outdated")),
        "modified": sum(1 for w in widgets if w.get("modified")),
        "widgets": widgets,
    })


def cmd_login(args):
    token = args.token

    if token:
        # Manual token login (legacy compat — treat as id_token with no refresh)
        from .cloud import login_with_credentials
        result = login_with_credentials(token, "", "")
        if "error" in result:
            err(result)
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
            id_token = params.get("id_token", [""])[0]
            if id_token:
                received["id_token"] = id_token
                received["refresh_token"] = params.get("refresh_token", [""])[0]
                received["signing_key"] = params.get("signing_key", [""])[0]
                received["handle"] = params.get("handle", [""])[0]
                received["client_id"] = params.get("client_id", [""])[0]
                received["client_secret"] = params.get("client_secret", [""])[0]
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
    print(f"  Logged in as @{handle}")

    # --- TOS check ---
    _check_and_prompt_tos()

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
            err({"error": "Provide a widget_id when using --lib"})
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
        if not widget:
            err({"error": f"Widget '{widget_id}' not found in library."})
        path = widget["path"]
    else:
        path = _resolve_widget(args.path)
        widget_id = args.widget_id
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
    from .checkin import _scan_contamination
    scan = _scan_contamination(path, tech_stack)

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
    result = push(path, widget_id, visibility=args.visibility)
    if "error" in result:
        err(result)

    nid      = result.get("namespaced_id", widget_id)
    version  = result.get("version", "?")
    vis      = result.get("visibility", "public")
    vis_icon = "🔒" if vis == "private" else "🌐"
    print(f"\n  ✓ Published {nid}  ·  v{version}  ·  {vis_icon} {vis}\n")


def cmd_rate(args):
    result = _carto().add_review(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
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
    if not args.confirm:
        err({"error": f"This will remove '{args.widget_id}' from the cloud registry. Add --confirm to proceed."})
    result = cloud.delete_widget(args.widget_id)
    if "error" in result:
        err(result)
    print(f"\n  Unpublished {args.widget_id} from cloud. Local copy unchanged.\n")


def cmd_cloud_rate(args):
    """Rate a cloud widget."""
    from . import cloud, auth
    if not auth.is_authenticated():
        err({"error": "Not authenticated. Run: cartograph login"})

    # Parse @handle/widget_id or plain widget_id
    widget_id = args.widget_id
    if widget_id.startswith("@"):
        parts = widget_id[1:].split("/", 1)
        if len(parts) != 2:
            err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner, widget_id = parts
    else:
        # Look up owner from cloud search
        results = cloud.search(widget_id, top_k=1)
        widgets = results.get("widgets", [])
        match = next((w for w in widgets if w.get("id") == widget_id), None)
        if not match:
            err({"error": f"Widget '{widget_id}' not found on cloud."})
        owner = match.get("owner", "")

    result = cloud.rate_widget(owner, widget_id, args.score, args.comment)
    if "error" in result:
        err(result)
    print(f"\n  Rated {args.widget_id}: {args.score}/5\n")


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

    # --- Language engines (auto-discovered) ---
    from .languages.registry import _ENGINES
    for lang_name, engine in sorted(_ENGINES.items()):
        available, message = engine.check_available()
        lang_checks = []
        if available:
            lang_checks.append((lang_name, True, "ready", None))
        else:
            lang_checks.append((lang_name, False, "not ready", message))
        groups.append((lang_name.capitalize(), lang_checks))

    # --- Render ---
    all_checks = [c for _, checks in groups for c in checks]
    passed = sum(1 for c in all_checks if c[1])
    total = len(all_checks)
    all_ok = passed == total

    print()
    for group_name, checks in groups:
        print(f"  {group_name}")
        for label, ok, detail, fix in checks:
            mark = "✓" if ok else "✗"
            print(f"    [{mark}] {label:<12}  {detail}")
            if not ok and fix:
                print(f"          → {fix}")
        print()

    if all_ok:
        print(f"  No issues found.\n")
    else:
        issues = total - passed
        print(f"  {issues} issue{'s' if issues > 1 else ''} found.\n")
        sys.exit(1)


_SETUP_INSTRUCTIONS = """\
## Cartograph

Cartograph is a widget library manager. Widgets are reusable, self-contained
code modules with tests, examples, and metadata. When installed into a project
they live under `cg/<widget_id>/`.

Before writing reusable, self-contained logic, search the library first.

### Widget structure
```
cg/<widget_id>/
  widget.json          metadata, version, dependencies
  src/                 source code
  tests/               test files (80%+ coverage required)
  examples/            example_usage.* (must run), usage_hint.* (optional)
```

widget_id format: `<domain>-<name>-<language>` e.g. `backend-retry-backoff-python`

Do not edit installed widget files directly - local edits are overwritten on
update. Wrap or extend in your own code instead.

### Commands
`<arg>` = required  `[arg]` = optional  defaults shown where relevant

**Find and use widgets**

    cartograph search <query>
        [--domain backend|data|ml|security|infra|frontend|universal]
        [--language python|javascript|typescript|nim]

    cartograph inspect <widget_id>
        [--source]         include source files
        [--reviews]        include review comments
        [--all-versions]   list full version history
        [--version X]      inspect a specific version

    cartograph install <widget_id> [--target .] [--version X]
    cartograph uninstall <widget_id> [--target .]
    cartograph upgrade <widget_id> [--target .] [--version X]
    cartograph status [widget_id] [--target .]
    cartograph rate <widget_id> <score 1-5> [--comment "..."] [--target .]

**Create and publish widgets**

    cartograph create <widget_id>
        --language python|javascript|typescript|nim    REQUIRED
        --domain backend|data|ml|security|infra|frontend|universal  REQUIRED
        [--name "Display Name"] [--target .]

    cartograph validate [path] [--lib]   path defaults to .
    cartograph checkin [path]            path defaults to .
        --reason "what changed and why"  REQUIRED
        [--bump patch|minor|major]       defaults to minor
        [--publish]                      also publish to cloud

    cartograph delete <widget_id> [--confirm]

**Cloud registry**

    cartograph cloud publish [widget_id] [path]
        [--lib]                          publish from library by ID
        [--visibility public|private]    defaults to public

    cartograph cloud unpublish <widget_id> --confirm
    cartograph cloud sync [--dry-run]
    cartograph cloud rate <@handle/widget_id> <score 1-5> [--comment "..."]

**Library and account**

    cartograph stats
    cartograph doctor
    cartograph login [--token X]
    cartograph logout
    cartograph whoami
    cartograph dashboard
"""

_AGENT_FILENAMES = {
    "claude":       "CLAUDE.md",
    "codex":        "AGENTS.md",
    "gemini":       "GEMINI.md",
    "antigravity":  "GEMINI.md",
    "cursor":       os.path.join(".cursor", "rules", "cartograph.mdc"),
}





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
    from packaging.version import Version, InvalidVersion

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
    cloud_by_id = {w["id"]: w for w in cloud_widgets_list}

    all_ids = sorted(set(local_widgets) | set(cloud_by_id))
    if not all_ids:
        print("\n  Nothing to sync — library and cloud are both empty.\n")
        return

    def _ver(s):
        try:
            return Version(s)
        except (InvalidVersion, TypeError):
            return Version("0.0.0")

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


def cmd_setup(args):
    agent = args.agent
    write = args.write

    if write and not agent:
        print("\n  --write requires --agent. Example:")
        print("    cartograph setup --write --agent claude\n")
        print("  Supported agents: claude, codex, gemini, antigravity, cursor")
        sys.exit(1)

    if not agent:
        print(_SETUP_INSTRUCTIONS)
        print("  # To write to a file, run: cartograph setup --write --agent <agent>")
        return

    content  = _SETUP_INSTRUCTIONS
    filename = _AGENT_FILENAMES[agent]

    if agent == "cursor":
        content = _cursor_mdc(content)

    if write:
        target_dir = os.getcwd()
        filepath = os.path.join(target_dir, filename)
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

        marker = "## Cartograph"
        if os.path.exists(filepath):
            existing = open(filepath).read()
            if marker in existing:
                print(f"\n  Cartograph section already exists in {filepath}")
                print(f"  Remove the existing ## Cartograph section and re-run to replace it.\n")
                sys.exit(1)
        with open(filepath, "a") as f:
            f.write("\n" + content)
        print(f"\n  Written to {filepath}\n")
    else:
        print(content)
        print(f"  # Add this to your {filename}, or run: cartograph setup --write")


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
            "help": "Rate an installed widget",
            "handler": cmd_rate,
            "args": [
                {"name": "widget_id"},
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
                {"name": "widget_id"},
                {"name": "--language", "required": True, "choices": supported_languages()},
                {"name": "--domain", "required": True,
                 "choices": ["backend", "data", "ml", "security", "infra", "frontend", "universal"]},
                {"name": "--name", "default": None, "help": "Human-readable display name"},
                {"name": "--target", "default": ".", "help": "Where to create the widget (default: .)"},
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
                {"name": "--visibility", "default": "public", "choices": ["public", "private"]},
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
            "name": "cloud sync",
            "help": "Reconcile local library with cloud",
            "handler": cmd_sync,
            "args": [
                {"name": "--dry-run", "action": "store_true", "default": False, "dest": "dry_run"},
            ],
        },
        {
            "name": "cloud rate",
            "help": "Rate a cloud widget",
            "handler": cmd_cloud_rate,
            "args": [
                {"name": "widget_id", "help": "Widget ID (e.g. @handle/widget-id)"},
                {"name": "score", "type": int, "help": "Score from 1 to 5"},
                {"name": "--comment", "default": "", "help": "Optional review comment"},
            ],
        },
    ])

    cli.add_commands("Config", [
        {
            "name": "setup",
            "help": "Generate and write agent instructions",
            "handler": cmd_setup,
            "args": [
                {"name": "--agent", "default": None,
                 "choices": ["claude", "codex", "gemini", "antigravity", "cursor"]},
                {"name": "--write", "action": "store_true", "default": False},
            ],
        },
        {
            "name": "login",
            "help": "Authenticate with the Cartograph cloud registry",
            "handler": cmd_login,
            "args": [
                {"name": "--token", "default": None, "help": "API token"},
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
