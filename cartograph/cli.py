"""
Cartograph CLI — manage your widget library from the terminal.

Every command that takes a path defaults to the current directory (.).
Output is always JSON so both humans and AI agents can consume it.
"""

import argparse
import json
import os
import shutil
import sys
import urllib.parse
import zipfile
from io import BytesIO


def _out(result: dict) -> None:
    print(json.dumps(result, indent=2))


def _err(result: dict) -> None:
    _out(result)
    sys.exit(1)


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
    If the path doesn't exist or lacks widget.json, tries cartograph/<path>/
    from the current directory.
    """
    resolved = os.path.abspath(path)
    if os.path.isfile(os.path.join(resolved, "widget.json")):
        return resolved

    # Try cartograph/<path>/ from cwd (handles bare widget_id like "logic-test-python")
    candidate = os.path.join(os.getcwd(), "cartograph", path)
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
    _out(merged)


def cmd_inspect(args):
    result = _carto().inspect(
        widget_id=args.widget_id,
        show_source=args.source,
        show_all_versions=args.all_versions,
        show_reviews=args.reviews,
        version=getattr(args, "version", None),
    )
    _out(result)


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
        _err(result)
    _out(result)
    _cloud_install_note(result)


def cmd_uninstall(args):
    result = _carto().uninstall(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)


def cmd_upgrade(args):
    result = _carto().upgrade(
        widget_id=args.widget_id,
        target_dir=_resolve(args.target),
        version=args.version,
    )
    if result.get("status") == "error":
        _err(result)
    _out(result)
    _cloud_install_note(result)


def cmd_delete(args):
    result = _carto().delete(
        widget_id=args.widget_id,
        confirm=args.confirm,
    )
    if result.get("status") == "error":
        _err(result)

    # Also remove from cloud if published
    if result.get("status") == "success":
        from . import cloud, auth
        if auth.is_authenticated() and cloud.is_available():
            cloud_result = cloud.delete_widget(args.widget_id)
            if "error" not in cloud_result:
                result["cloud"] = "deleted"
            # Silently skip if not on cloud (404)

    _out(result)


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
        _err(result)
    _out(result)


def _resolve_widget_path(args) -> str:
    """Resolve a widget path from either --lib <widget_id> or a filesystem path."""
    if getattr(args, "lib", False):
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == args.path), None)
        if not widget:
            _err({"error": f"Widget '{args.path}' not found in library. Use 'cartograph search' to browse."})
        return widget["path"]
    return _resolve_widget(args.path)


def cmd_validate(args):
    path = _resolve_widget_path(args)
    _preflight_from_path(path)
    result = _carto().validate_item(path=path)
    if result.get("status") == "error":
        _err(result)
    _out(result)


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
        _err(result)
    _out(result)

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
            _err(result)
        _out(result)
        return

    # No widget_id — scan all installed widgets
    install_dir = os.path.join(target, "cartograph")
    if not os.path.isdir(install_dir):
        _err({"error": f"No cartograph/ directory found at {target}"})

    widget_ids = [
        d for d in os.listdir(install_dir)
        if os.path.isfile(os.path.join(install_dir, d, "widget.json"))
    ]

    if not widget_ids:
        _out({"installed": 0, "widgets": []})
        return

    carto = _carto()
    widgets = []
    for wid in sorted(widget_ids):
        r = carto.widget_status(widget_id=wid, target_dir=target)
        widgets.append(r)

    _out({
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
            _err(result)
        _out(result)
        return

    # No token given — use browser-based OAuth flow
    if not sys.stdin.isatty():
        _err({"error": "Provide a token with --token or set CARTOGRAPH_TOKEN"})

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
        _err({"error": "Authentication timed out or was cancelled."})

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

    _out({"status": "success", "owner": handle})


def cmd_whoami(args):
    from .auth import is_authenticated
    if not is_authenticated():
        _out({"authenticated": False})
        return
    from .cloud import whoami
    result = whoami()
    if "error" in result:
        _err(result)
    _out({"authenticated": True, **result})


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
        _out({"status": "already_logged_out"})
        return
    clear_token()
    _out({"status": "success", "message": "Logged out."})


def cmd_cloud_publish(args):
    from .auth import is_authenticated
    if not is_authenticated():
        _err({"error": "Not authenticated. Run: cartograph login"})

    if getattr(args, "lib", False):
        # Resolve path from library by widget_id
        widget_id = args.widget_id
        if not widget_id:
            _err({"error": "Provide a widget_id when using --lib"})
        carto = _carto()
        widget = next((w for w in carto.widgets if w["id"] == widget_id), None)
        if not widget:
            _err({"error": f"Widget '{widget_id}' not found in library."})
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
            _err({"error": "Could not determine widget_id. Pass it explicitly or use --lib."})

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
            _err(validate_result)

    # Contamination scan — same gate as checkin
    from .checkin import _scan_contamination
    scan = _scan_contamination(path, tech_stack)

    if scan["blocks"]:
        _err({
            "error": "Push blocked: project-specific content detected.",
            "blocks": scan["blocks"],
        })

    if scan["warnings"] and not getattr(args, "override_warnings", False):
        _err({
            "status": "warnings",
            "message": "Push paused: potential contamination found. "
                       "Review warnings and re-run with --override-warnings and --override-reason.",
            "warnings": scan["warnings"],
        })

    if getattr(args, "override_warnings", False) and not getattr(args, "override_reason", None):
        _err({"error": "Push with --override-warnings requires --override-reason."})

    from .cloud import push
    result = push(path, widget_id, visibility=args.visibility)
    if "error" in result:
        _err(result)

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
        _err(result)
    _out(result)


def cmd_cloud_unpublish(args):
    """Remove a widget from the cloud registry (keeps local copy)."""
    from . import cloud, auth
    if not auth.is_authenticated():
        _err({"error": "Not authenticated. Run: cartograph login"})
    if not args.confirm:
        _err({"error": f"This will remove '{args.widget_id}' from the cloud registry. Add --confirm to proceed."})
    result = cloud.delete_widget(args.widget_id)
    if "error" in result:
        _err(result)
    print(f"\n  Unpublished {args.widget_id} from cloud. Local copy unchanged.\n")


def cmd_cloud_rate(args):
    """Rate a cloud widget."""
    from . import cloud, auth
    if not auth.is_authenticated():
        _err({"error": "Not authenticated. Run: cartograph login"})

    # Parse @handle/widget_id or plain widget_id
    widget_id = args.widget_id
    if widget_id.startswith("@"):
        parts = widget_id[1:].split("/", 1)
        if len(parts) != 2:
            _err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner, widget_id = parts
    else:
        # Look up owner from cloud search
        results = cloud.search(widget_id, top_k=1)
        widgets = results.get("widgets", [])
        match = next((w for w in widgets if w.get("id") == widget_id), None)
        if not match:
            _err({"error": f"Widget '{widget_id}' not found on cloud."})
        owner = match.get("owner", "")

    result = cloud.rate_widget(owner, widget_id, args.score, args.comment)
    if "error" in result:
        _err(result)
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
            _err({"error": f"Invalid format: '{widget_id}'. Use @handle/widget_id."})
        owner_handle, base_id = parts

    carto = _carto()

    # If no version specified, list available versions
    if not version:
        if owner_handle:
            # Cloud: list versions from GCS
            result = cloud.get_versions(owner_handle, base_id)
            if "error" in result:
                _err(result)
            versions = result.get("versions", [])
            current = result.get("current_version", "?")
            if not versions:
                _err({"error": f"No versions found for {widget_id}"})
            print(f"\n  Versions for {widget_id} (current: {current}):\n")
            for v in versions:
                marker = " ← current" if v == current else ""
                print(f"    {v}{marker}")
            print()
        else:
            # Local: list from history/
            item = next((w for w in carto.widgets if w["id"] == base_id), None)
            if not item:
                _err({"error": f"Widget '{base_id}' not found in library"})
            import os
            history_dir = os.path.join(item["path"], "history")
            if not os.path.isdir(history_dir):
                _err({"error": f"No version history for '{base_id}'"})
            versions = sorted(os.listdir(history_dir), reverse=True)
            current = item.get("version", "?")
            if not versions:
                _err({"error": f"No version history for '{base_id}'"})
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
        _err({"error": f"Could not rollback '{widget_id}' — not found locally or on cloud"})

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

    # --- Python ---
    import sys
    py_checks = []
    py_checks.append(("Python", True, sys.executable, None))

    ok, out = run([sys.executable, "-m", "pytest", "--version"])
    py_checks.append(("pytest", ok,
                       out.splitlines()[0] if ok else "not found",
                       "pip install pytest" if not ok else None))

    ok, out = run([sys.executable, "-m", "coverage", "--version"])
    py_checks.append(("coverage", ok,
                       out.splitlines()[0] if ok else "not found",
                       "pip install coverage" if not ok else None))
    groups.append(("Python", py_checks))

    # --- JavaScript ---
    js_checks = []
    node = shutil.which("node")
    if node:
        ok, out = run(["node", "--version"])
        version_str = out.strip()
        try:
            major = int(version_str.lstrip("v").split(".")[0])
            version_ok = major >= 18
        except ValueError:
            version_ok = False
        js_checks.append(("Node.js", version_ok,
                           version_str if version_ok else f"{version_str} (need ≥18)",
                           "Install Node.js 18+ — nodejs.org" if not version_ok else None))
    else:
        js_checks.append(("Node.js", False, "not found", "Install Node.js 18+ — nodejs.org"))

    npx = shutil.which("npx") or shutil.which("npx.cmd")
    js_checks.append(("npx", npx is not None,
                       "found" if npx else "not found",
                       "Reinstall Node.js — npx ships with it" if not npx else None))

    groups.append(("JavaScript", js_checks))

    # --- Nim ---
    nim_checks = []
    nim = shutil.which("nim")
    if nim:
        ok, out = run(["nim", "--version"])
        version_line = out.splitlines()[0] if out else ""
        try:
            version_str = version_line.split("Version")[1].strip().split()[0]
            major, minor = int(version_str.split(".")[0]), int(version_str.split(".")[1])
            version_ok = (major, minor) >= (2, 0)
        except Exception:
            version_str, version_ok = version_line, False
        nim_checks.append(("nim", version_ok,
                           version_str if version_ok else f"{version_str} (need ≥2.0)",
                           "Install Nim 2.0+ — nim-lang.org" if not version_ok else None))
    else:
        nim_checks.append(("nim", False, "not found", "Install Nim 2.0+ — nim-lang.org"))

    nimble = shutil.which("nimble")
    if nimble:
        ok, out = run(["nimble", "--version"])
        version_str = out.splitlines()[0].strip() if out else "found"
        nim_checks.append(("nimble", True, version_str, None))
    else:
        nim_checks.append(("nimble", False, "not found", "Reinstall Nim — nimble ships with it"))
    groups.append(("Nim", nim_checks))

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
they live under `cartograph/<widget_id>/`.

Before writing reusable, self-contained logic, search the library first.

### Widget structure
```
cartograph/<widget_id>/
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
        _err({"error": "Not authenticated. Run: cartograph login"})
    if not cloud.is_available():
        _err({"error": "Cloud registry is unreachable."})

    dry_run = args.dry_run
    carto = _carto()
    local_widgets = {w["id"]: w for w in carto.widgets}

    profile = cloud.whoami()
    if "error" in profile:
        _err(profile)
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
# Parser
# ---------------------------------------------------------------------------

_COMMAND_GROUPS = [
    ("Use widgets", [
        ("search",    "Search the widget library"),
        ("inspect",   "Show widget details"),
        ("install",   "Install a widget into your project"),
        ("uninstall", "Remove a widget from your project"),
        ("upgrade",   "Upgrade an installed widget to the latest version"),
        ("status",    "Check installed widget(s) - omit widget_id to scan all"),
        ("rate",      "Rate an installed widget"),
    ]),
    ("Build widgets", [
        ("create",   "Scaffold a new widget"),
        ("validate", "Run the validation pipeline on a widget"),
        ("checkin",  "Check a widget into the library (--publish to also publish)"),
        ("rollback", "Roll back a widget to a previous version (local + cloud)"),
        ("delete",   "Remove a widget from the library (and cloud if published)"),
    ]),
    ("Cloud registry", [
        ("cloud publish",   "Publish a widget to the cloud registry"),
        ("cloud unpublish", "Remove a widget from the cloud (keeps local)"),
        ("cloud sync",      "Reconcile local library with cloud"),
        ("cloud rate",      "Rate a cloud widget"),
    ]),
    ("Config", [
        ("setup",     "Generate and write agent instructions"),
        ("login",     "Authenticate with the Cartograph cloud registry"),
        ("logout",    "Remove stored cloud credentials"),
        ("whoami",    "Show current authenticated user"),
        ("dashboard", "Open local widget dashboard in browser"),
        ("stats",     "Show library statistics"),
        ("doctor",    "Check language engine dependencies"),
    ]),
]


def _grouped_help():
    use_color = sys.stdout.isatty()
    if use_color:
        g, r = "\033[32m", "\033[0m"  # green, reset
    else:
        g, r = "", ""
    lines = ["", "usage: cartograph <command> [options]", ""]
    for group_name, commands in _COMMAND_GROUPS:
        lines.append(f"  {group_name}:")
        for cmd, desc in commands:
            lines.append(f"    {g}{cmd:<12s}{r} {desc}")
        lines.append("")
    lines.append(f"  Run '{g}cartograph <command> -h{r}' for command-specific help.")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    from . import __version__
    parser = argparse.ArgumentParser(
        prog="cartograph",
        description="Cartograph widget library manager",
        usage=argparse.SUPPRESS,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", default=False)
    parser.add_argument("-v", "--version", action="version",
                        version=f"cartograph {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # --- Use widgets ---

    p = sub.add_parser("search", help="Search the widget library")
    p.add_argument("query", help="Search query")
    p.add_argument("--domain", default=None, help="Filter by domain")
    p.add_argument("--language", default=None, help="Filter by language")
    p.add_argument("--top-k", type=int, default=10, dest="top_k")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("inspect", help="Show widget details")
    p.add_argument("widget_id")
    p.add_argument("--source", action="store_true", help="Include source files")
    p.add_argument("--all-versions", action="store_true", dest="all_versions")
    p.add_argument("--reviews", action="store_true")
    p.add_argument("--version", default=None, help="Inspect a specific historical version (e.g. 1.2.0)")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("install", help="Install a widget into your project")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="Remove a widget from your project")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("upgrade", help="Upgrade an installed widget to the latest version")
    p.add_argument("widget_id")
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.add_argument("--version", default=None)
    p.set_defaults(func=cmd_upgrade)

    p = sub.add_parser("status", help="Check installed widget(s) - omit widget_id to scan all")
    p.add_argument("widget_id", nargs="?", default=None)
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("rate", help="Rate an installed widget")
    p.add_argument("widget_id")
    p.add_argument("score", type=float, help="Score from 1.0 to 5.0")
    p.add_argument("--comment", default=None)
    p.add_argument("--target", default=".", help="Project root (default: .)")
    p.set_defaults(func=cmd_rate)

    # --- Build widgets ---

    p = sub.add_parser("create", help="Scaffold a new widget")
    p.add_argument("widget_id")
    from .languages.registry import supported_languages
    p.add_argument("--language", required=True, choices=supported_languages())
    p.add_argument("--domain", required=True,
                   choices=["backend", "data", "ml", "security", "infra", "frontend", "universal"])
    p.add_argument("--name", default=None, help="Human-readable display name")
    p.add_argument("--target", default=".", help="Where to create the widget (default: .)")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("validate", help="Run the validation pipeline on a widget")
    p.add_argument("path", nargs="?", default=".", help="Widget directory or widget_id with --lib (default: .)")
    p.add_argument("--lib", action="store_true", help="Treat path as a library widget_id")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("checkin", help="Check a widget into the library")
    p.add_argument("path", nargs="?", default=".", help="Widget directory (default: .)")
    p.add_argument("--reason", required=True, help="What changed and why")
    p.add_argument("--bump", default="minor", choices=["major", "minor", "patch"],
                   help="Version bump type (default: minor)")
    p.add_argument("--publish", action="store_true",
                   help="Publish to cloud after checkin (even if not previously published)")
    p.add_argument("--override-warnings", action="store_true", dest="override_warnings")
    p.add_argument("--override-reason", default=None, dest="override_reason")
    p.set_defaults(func=cmd_checkin)

    p = sub.add_parser("delete", help="Remove a widget from the library")
    p.add_argument("widget_id")
    p.add_argument("--confirm", action="store_true",
                   help="Actually delete the widget from the library (irreversible)")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("rollback", help="Roll back a widget to a previous version")
    p.add_argument("widget_id", help="Widget ID (local) or @handle/widget_id (cloud)")
    p.add_argument("--version", default=None, help="Version to roll back to (omit to list available)")
    p.add_argument("--reason", default="", help="Reason for rollback")
    p.set_defaults(func=cmd_rollback)

    # --- Cloud subcommands ---

    cloud_parser = sub.add_parser("cloud", help="Cloud registry operations")
    cloud_sub = cloud_parser.add_subparsers(dest="cloud_command")

    p = cloud_sub.add_parser("publish", help="Publish a validated widget to the cloud registry")
    p.add_argument("widget_id", nargs="?", default=None,
                   help="Widget ID (required with --lib, inferred from widget.json otherwise)")
    p.add_argument("path", nargs="?", default=".",
                   help="Widget directory (default: .)")
    p.add_argument("--lib", action="store_true", help="Publish a widget from the library by ID")
    p.add_argument("--visibility", default="public", choices=["public", "private"],
                   help="Registry visibility (default: public)")
    p.add_argument("--override-warnings", action="store_true", dest="override_warnings")
    p.add_argument("--override-reason", default=None, dest="override_reason")
    p.set_defaults(func=cmd_cloud_publish)

    p = cloud_sub.add_parser("unpublish", help="Remove a widget from the cloud registry (keeps local)")
    p.add_argument("widget_id")
    p.add_argument("--confirm", action="store_true",
                   help="Actually remove from cloud (required)")
    p.set_defaults(func=cmd_cloud_unpublish)

    p = cloud_sub.add_parser("sync", help="Reconcile local library with cloud (publish newer, download newer)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Show what would happen without making changes")
    p.set_defaults(func=cmd_sync)

    p = cloud_sub.add_parser("rate", help="Rate a cloud widget")
    p.add_argument("widget_id", help="Widget ID (e.g. @handle/widget-id or just widget-id)")
    p.add_argument("score", type=int, help="Score from 1 to 5")
    p.add_argument("--comment", default="", help="Optional review comment")
    p.set_defaults(func=cmd_cloud_rate)

    cloud_parser.set_defaults(func=lambda args: cloud_parser.print_help())

    # --- Config ---

    p = sub.add_parser("setup", help="Generate and write agent instructions")
    p.add_argument("--agent", default=None,
                   choices=["claude", "codex", "gemini", "antigravity", "cursor"],
                   help="Target agent: claude=CLAUDE.md, codex=AGENTS.md, gemini/antigravity=GEMINI.md, cursor=.cursor/rules/cartograph.mdc")
    p.add_argument("--write", action="store_true",
                   help="Write to the project's agent config file")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("login", help="Authenticate with the Cartograph cloud registry")
    p.add_argument("--token", default=None,
                   help="API token (prompted interactively if omitted in a terminal)")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="Remove stored cloud credentials")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("whoami", help="Show current authenticated user")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("dashboard", help="Open local widget dashboard in browser")
    p.add_argument("--port", type=int, default=0, help="Override port for this session")
    p.add_argument("--set-port", type=int, metavar="PORT", help="Permanently set the dashboard port")
    p.add_argument("--stop", action="store_true", help="Stop a running dashboard")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("stats", help="Show library statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("doctor", help="Check language engine dependencies")
    p.set_defaults(func=cmd_doctor)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.help or not args.command:
        print(_grouped_help())
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
