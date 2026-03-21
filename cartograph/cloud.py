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
Install paths remain cartograph/<widget-id>/ regardless of source.
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

def _headers() -> dict:
    from .auth import get_token
    token = get_token()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _registry_url() -> str:
    from .auth import get_registry_url
    return get_registry_url().rstrip("/")


def _get(path: str) -> dict:
    url = _registry_url() + path
    req = urllib.request.Request(url, headers=_headers())
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


def _post_multipart(path: str, fields: dict, file_data: bytes, filename: str) -> dict:
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
    headers = _headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary.decode()}"

    url = _registry_url() + path
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


def search(query: str, domain_filter: str | None = None,
           language_filter: str | None = None, top_k: int = 10) -> dict:
    """
    Search the cloud registry.

    Returns {"widgets": [...], "source": "cloud"} on success,
    or {"error": ..., "widgets": []} on failure so the caller can still
    merge partial results.
    """
    from .auth import is_authenticated
    if not is_authenticated():
        return {"widgets": [], "source": "cloud", "skipped": "not authenticated"}

    params = f"?q={urllib.parse.quote(query)}&top_k={top_k}"
    if domain_filter:
        params += f"&domain={urllib.parse.quote(domain_filter)}"
    if language_filter:
        params += f"&language={urllib.parse.quote(language_filter)}"

    result = _get(f"/v1/widgets/search{params}")
    if "error" in result:
        return {"widgets": [], "source": "cloud", "error": result["error"]}

    return {"widgets": result.get("widgets", []), "source": "cloud"}


def push(widget_path: str, widget_id: str, visibility: str = "public") -> dict:
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

    # Bundle widget files into a zip in memory
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(widget_path):
            # Skip generated dirs and stamp itself
            rel_root = os.path.relpath(root, widget_path)
            skip_dirs = {"__pycache__", ".pytest_cache", "history", ".git", "node_modules"}
            if any(part in skip_dirs for part in rel_root.split(os.sep)):
                continue
            for fname in files:
                if fname == ".validation_stamp.json":
                    continue
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, widget_path)
                zf.write(fpath, arcname)
    zip_bytes = buf.getvalue()

    fields = {
        "widget_id": widget_id,
        "visibility": visibility,
        "stamp": json.dumps(signed_stamp),
    }

    return _post_multipart(
        f"/v1/widgets/{urllib.parse.quote(widget_id, safe='')}/publish",
        fields=fields,
        file_data=zip_bytes,
        filename=f"{widget_id}.zip",
    )


def login_with_token(token: str) -> dict:
    """
    Validate a token against the registry and save it if valid.

    Returns {"status": "success", "owner": ...} or {"error": ...}.
    """
    from .auth import save_token, get_registry_url

    url = get_registry_url().rstrip("/") + "/v1/auth/me"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
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

    save_token(token)
    return {"status": "success", "owner": data.get("owner") or data.get("username", "unknown")}
