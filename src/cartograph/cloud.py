"""
Cartograph cloud registry client.

All network activity is in this module.  Everything uses urllib.request so
there are no extra dependencies.  If the user is not authenticated or the
registry is unreachable, functions degrade gracefully and return structured
error dicts rather than raising.

Cloud is additive to local:
- search() merges cloud results with local results (caller deduplicates)
- push() sends a validated widget + signed stamp to the registry
- is_available() does a cheap health check before trying anything

Widget IDs in cloud results are namespaced as @owner/widget-id.
Install paths remain cg/<widget-id>/ regardless of source.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO

log = logging.getLogger("cartograph")

_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _headers(registry_url: str | None = None) -> dict:
    from .auth import get_token
    token = get_token(registry_url)
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _registry_url() -> str:
    from .auth import get_registry_url
    return get_registry_url().rstrip("/")


def _get(path: str, registry_url: str | None = None) -> dict:
    base = registry_url.rstrip("/") if registry_url else _registry_url()
    url = base + path
    req = urllib.request.Request(url, headers=_headers(registry_url))
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return {"error": body.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, data: dict) -> dict:
    url = _registry_url() + path
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return {"error": body.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def _patch(path: str, data: dict) -> dict:
    url = _registry_url() + path
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers=_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return {"error": body.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def _post_multipart(path: str, fields: dict, file_data: bytes, filename: str,
                    registry_url: str | None = None) -> dict:
    """POST multipart/form-data with a single file attachment."""
    boundary = b"cartograph_boundary_" + os.urandom(8).hex().encode()
    body_parts = []

    for key, value in fields.items():
        body_parts.append(
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="' + key.encode() + b'"\r\n\r\n'
            + str(value).encode() + b"\r\n"
        )

    body_parts.append(
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + filename.encode() + b'"\r\n'
        b"Content-Type: application/zip\r\n\r\n"
        + file_data + b"\r\n"
    )
    body_parts.append(b"--" + boundary + b"--\r\n")

    body = b"".join(body_parts)
    headers = _headers(registry_url)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary.decode()}"

    base = registry_url.rstrip("/") if registry_url else _registry_url()
    url = base + path
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_resp = {}
        try:
            body_resp = json.loads(e.read())
        except Exception:
            pass
        return {"error": body_resp.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return True if the registry responds to a health check."""
    try:
        url = _registry_url() + "/health"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _validate_widgets(widgets: list, context: str = "") -> list:
    """
    Validate widget objects returned by the cloud registry.

    Required fields (widget is dropped if missing or wrong type):
      - id      (str, format "@owner/widget-id") — used for dedup and lookup
      - version (str, semver)                    — used for sync and upgrade logic

    Expected fields (used by CLI with .get() defaults, should be present for full UX):
      - name, domain, language, description, tags, rating, owner, install_count

    Optional/additive fields (passed through untouched — registry may add freely):
      - relevance_score  defaults to 0 if absent in search results
      - stale, deprecated, last_updated, or any future annotations

    Malformed widgets are dropped with a warning log rather than failing the
    whole response. A broken registry is the registry owner's problem.
    """
    valid = []
    for w in widgets:
        wid = w.get("id", "")
        ver = w.get("version", "")
        if not isinstance(wid, str) or not wid:
            log.warning("Cloud%s: dropping widget missing 'id': %s", f" ({context})" if context else "", w)
            continue
        if not isinstance(ver, str) or not ver:
            log.warning("Cloud%s: dropping widget '%s' missing 'version'", f" ({context})" if context else "", wid)
            continue
        valid.append(w)
    return valid


def search(query: str, domain_filter: str | None = None,
           language_filter: str | None = None, top_k: int = 10,
           registry_url: str | None = None) -> dict:
    """
    Search the cloud registry (public — no auth required).

    Returns {"widgets": [...], "source": "cloud"} on success,
    or {"error": ..., "widgets": []} on failure so the caller can still
    merge partial results.
    """
    params = f"?q={urllib.parse.quote(query)}&top_k={top_k}"
    if domain_filter:
        params += f"&domain={urllib.parse.quote(domain_filter)}"
    if language_filter:
        params += f"&language={urllib.parse.quote(language_filter)}"

    result = _get(f"/v1/widgets/search{params}", registry_url=registry_url)
    if "error" in result:
        return {"widgets": [], "source": "cloud", "error": result["error"]}

    widgets = _validate_widgets(result.get("widgets", []), context="search")
    for w in widgets:
        w.setdefault("relevance_score", 0)
    return {"widgets": widgets, "source": "cloud"}


def search_users(query: str, top_k: int = 20) -> dict:
    """
    Search the cloud registry for users by handle/name.

    Returns {"users": [...]} on success, or {"error": ..., "users": []} on failure.
    """
    params = f"?q={urllib.parse.quote(query)}&top_k={top_k}"
    result = _get(f"/v1/users/search{params}")
    if "error" in result:
        return {"users": [], "error": result["error"]}
    return {"users": result.get("users", [])}


def push(widget_path: str, widget_id: str, visibility: str = "public",
         governance: str | None = None, registry_url: str | None = None) -> dict:
    """
    Push a validated widget to the cloud registry.

    Reads the validation stamp, signs it, bundles src/tests/examples/widget.json
    into a zip, and POSTs to the registry.

    Returns the registry response dict, or {"error": ...} on failure.
    """
    from .auth import is_authenticated
    from .validation_stamp import read_stamp
    from .trust import sign_stamp

    if not is_authenticated():
        return {"error": "Not authenticated. Run: cartograph login"}

    stamp = read_stamp(widget_path)
    if stamp is None:
        return {
            "error": (
                f"No validation stamp found at {widget_path}. "
                "Run 'cartograph validate' first."
            )
        }

    # Sign the stamp
    signature = sign_stamp(stamp)
    signed_stamp = {**stamp, "signature": signature}

    zip_bytes = _zip_widget(widget_path)

    # Send allowed extensions so the cloud can validate dynamically
    # instead of maintaining a hardcoded whitelist per language.
    from .languages.registry import allowed_extensions
    fields = {
        "widget_id": widget_id,
        "visibility": visibility,
        "stamp": json.dumps(signed_stamp),
        "allowed_extensions": json.dumps(sorted(allowed_extensions())),
    }
    if governance:
        fields["governance"] = governance

    return _post_multipart(
        f"/v1/widgets/{urllib.parse.quote(widget_id, safe='')}/publish",
        fields=fields,
        file_data=zip_bytes,
        filename=f"{widget_id}.zip",
        registry_url=registry_url,
    )


def whoami() -> dict:
    """Return the current user's profile, or {"error": ...}."""
    return _get("/v1/auth/me")


def inspect(owner_handle: str, widget_id: str, source: bool = False,
            registry_url: str | None = None) -> dict:
    """Inspect a cloud widget. Public widgets don't require auth.

    Pass source=True to include extracted src/ file contents in the result.
    """
    path = f"/v1/widgets/{urllib.parse.quote(owner_handle)}/{urllib.parse.quote(widget_id)}"
    if source:
        path += "?include_source=true"
    return _get(path, registry_url=registry_url)


def download_widget(owner_handle: str, widget_id: str,
                    registry_url: str | None = None) -> dict:
    """Download a widget zip from the cloud registry.

    Returns {"zip_bytes": bytes, "version": str} on success,
    or {"error": ...} on failure.
    """
    base = registry_url.rstrip("/") if registry_url else _registry_url()
    url = (
        base
        + f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/download"
    )
    headers = _headers(registry_url)
    headers["Accept"] = "application/zip"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            version = resp.headers.get("X-Widget-Version", "0.0.0")
            return {"zip_bytes": resp.read(), "version": version}
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return {"error": body.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": f"Download failed: {e}"}


def registry_info() -> dict:
    """Fetch registry capabilities (e.g. whether it validates widgets).

    Returns {"validates": bool, ...} or {"error": ...}.
    Falls back to {"validates": False} if the endpoint doesn't exist yet.
    """
    result = _get("/v1/registry/info")
    if "error" in result:
        # Endpoint doesn't exist yet - assume no validation
        return {"validates": False}
    return result


def list_widgets(top_k: int = 500) -> dict:
    """Return all cloud widgets, or {"error": ...}."""
    return _get(f"/v1/widgets?top_k={top_k}")


def list_my_widgets() -> list[dict]:
    """Return the authenticated user's cloud widgets (public and private), or empty list on failure."""
    result = _get("/v1/auth/my-widgets")
    if "error" in result:
        return []
    return _validate_widgets(result.get("widgets", []), context="my-widgets")


def _delete(path: str) -> dict:
    url = _registry_url() + path
    req = urllib.request.Request(url, headers=_headers(), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return {"error": body.get("detail", str(e)), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def delete_widget(widget_id: str) -> dict:
    """Delete a widget from the cloud registry."""
    return _delete(f"/v1/widgets/{urllib.parse.quote(widget_id, safe='')}")


def get_reviews(owner_handle: str, widget_id: str) -> dict:
    """Fetch reviews for a cloud widget.

    Returns {"reviews": [...], "rating": avg, "review_count": n}
    or {"error": ..., "reviews": []}.
    """
    result = _get(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/reviews"
    )
    if "error" in result:
        return {"reviews": [], "error": result["error"]}
    return result


def rate_widget(owner_handle: str, widget_id: str, score: int, comment: str = "") -> dict:
    """Rate a cloud widget."""
    params = f"?score={score}"
    if comment:
        params += f"&comment={urllib.parse.quote(comment)}"
    return _post(f"/v1/widgets/{urllib.parse.quote(owner_handle)}/{urllib.parse.quote(widget_id)}/rate{params}", {})


def get_versions(owner_handle: str, widget_id: str) -> dict:
    """List available versions for a cloud widget.

    Returns {"versions": [...], "current_version": str}
    or {"error": ..., "versions": []}.
    """
    result = _get(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/versions"
    )
    if "error" in result:
        return {"versions": [], "error": result["error"]}
    return result


def rollback_widget(owner_handle: str, widget_id: str, version: str) -> dict:
    """Roll back a cloud widget to a previous version."""
    params = f"?version={urllib.parse.quote(version)}"
    return _post(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/rollback{params}",
        {},
    )


def get_tos() -> dict:
    """Fetch current TOS text and version from registry."""
    return _get("/v1/auth/tos")


def accept_tos() -> dict:
    """Accept the current TOS version."""
    return _post("/v1/auth/accept-tos", {})


def check_tos() -> dict:
    """Check if the current user has accepted the latest TOS.

    Returns {"accepted": bool, "current_version": int, "user_version": int}
    or {"error": ...}.
    """
    me = whoami()
    if "error" in me:
        return me
    tos = get_tos()
    if "error" in tos:
        return tos
    return {
        "accepted": me.get("tos_accepted", False),
        "current_version": tos.get("version", 0),
        "user_version": me.get("tos_version", 0),
    }


def login_with_credentials(id_token: str, refresh_token: str,
                           signing_key: str) -> dict:
    """
    Validate an ID token against the registry and save all credentials.

    Returns {"status": "success", "owner": ...} or {"error": ...}.
    """
    from .auth import save_credentials, get_registry_url

    url = get_registry_url().rstrip("/") + "/v1/auth/me"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {id_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "Invalid token."}
        return {"error": f"Registry error: {e.code}"}
    except Exception as e:
        return {"error": str(e)}

    save_credentials(id_token, refresh_token, signing_key)
    return {"status": "success", "owner": data.get("owner") or data.get("username", "unknown")}


# ---------------------------------------------------------------------------
# Governance & Proposals
# ---------------------------------------------------------------------------

def update_widget(owner_handle: str, widget_id: str, **kwargs) -> dict:
    """PATCH a cloud widget's settings (e.g. governance)."""
    return _patch(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}",
        kwargs,
    )


def _zip_widget(widget_path: str) -> bytes:
    """Bundle widget files into a zip in memory (shared by push and propose)."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(widget_path):
            rel_root = os.path.relpath(root, widget_path)
            skip_dirs = {"__pycache__", ".pytest_cache", "history", ".git", "node_modules"}
            if any(part in skip_dirs for part in rel_root.split(os.sep)):
                continue
            for fname in files:
                if fname in (".validation_stamp.json", ".file_stamp.json",
                             "reviews.json", "changelog.json"):
                    continue
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, widget_path)
                zf.write(fpath, arcname)
    return buf.getvalue()


def propose(widget_path: str, owner_handle: str, widget_id: str,
            reason: str, registry_url: str | None = None) -> dict:
    """Propose a contribution to someone else's widget.

    Validates locally, zips the widget, and POSTs to the contribute endpoint.
    Returns the registry response which can be:
    - published (auto-merged for open governance)
    - proposed (queued for review)
    - escalated (safeguards tripped, queued with violations)
    """
    from .auth import is_authenticated
    from .validation_stamp import read_stamp
    from .trust import sign_stamp

    if not is_authenticated():
        return {"error": "Not authenticated. Run: cartograph login"}

    stamp = read_stamp(widget_path)
    if stamp is None:
        return {"error": f"No validation stamp at {widget_path}. Run 'cartograph validate' first."}

    signature = sign_stamp(stamp)
    signed_stamp = {**stamp, "signature": signature}

    zip_bytes = _zip_widget(widget_path)

    from .languages.registry import allowed_extensions
    fields = {
        "reason": reason,
        "stamp": json.dumps(signed_stamp),
        "allowed_extensions": json.dumps(sorted(allowed_extensions())),
    }

    return _post_multipart(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/contribute",
        fields=fields,
        file_data=zip_bytes,
        filename=f"{widget_id}.zip",
        registry_url=registry_url,
    )


def my_proposals() -> dict:
    """List the authenticated user's proposals."""
    return _get("/v1/auth/my-proposals")


def list_proposals(owner_handle: str, widget_id: str) -> dict:
    """List proposals for a widget (owner view)."""
    return _get(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}/proposals"
    )


def accept_proposal(owner_handle: str, widget_id: str,
                    proposal_id: str) -> dict:
    """Accept a proposal."""
    return _post(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}"
        f"/proposals/{urllib.parse.quote(proposal_id)}/accept",
        {},
    )


def reject_proposal(owner_handle: str, widget_id: str,
                    proposal_id: str, reason: str = "") -> dict:
    """Reject a proposal."""
    params = f"?reason={urllib.parse.quote(reason)}" if reason else ""
    return _post(
        f"/v1/widgets/{urllib.parse.quote(owner_handle)}"
        f"/{urllib.parse.quote(widget_id)}"
        f"/proposals/{urllib.parse.quote(proposal_id)}/reject{params}",
        {},
    )
