"""Stdlib-only HTTP client with structured error dicts.

Built for self-describing API clients that want consistent error handling
without dragging in requests/httpx. Every method returns either the parsed
JSON body (dict) or an error dict with {"error": str, "status_code": int | None}.
No exceptions leak for HTTP or network failures.

    client = HTTPClient(
        base_url="https://registry.example.com",
        auth_headers=lambda url: {"Authorization": f"Bearer {token_for(url)}"},
    )
    result = client.get("/v1/widgets/some-id")
    if "error" in result:
        log.warning("lookup failed: %s", result["error"])
    else:
        use(result)

base_url is resolved once at construction. Per-call `base_url=` overrides it
when the same client needs to target a different host (e.g. multi-registry
setups where the URL is part of the dispatch decision).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


class HTTPClient:
    """HTTP client for JSON APIs. All methods return body dict or error dict."""

    def __init__(
        self,
        base_url: str,
        auth_headers: Callable[[str], dict] | None = None,
        default_timeout: float = 10.0,
        multipart_timeout: float = 30.0,
        user_agent: str | None = None,
    ):
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.auth_headers = auth_headers
        self.default_timeout = default_timeout
        self.multipart_timeout = multipart_timeout
        self.user_agent = user_agent

    def _resolve_base(self, base_url_override: str | None) -> str:
        if base_url_override:
            return base_url_override.rstrip("/")
        return self.base_url

    def _build_headers(self, resolved_base: str, extra: dict | None,
                       content_type: str | None = "application/json") -> dict:
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.auth_headers:
            try:
                auth = self.auth_headers(resolved_base) or {}
            except Exception:
                auth = {}
            headers.update(auth)
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        base_url: str | None,
        headers: dict | None,
        timeout: float | None,
        content_type: str | None,
    ) -> dict:
        resolved_base = self._resolve_base(base_url)
        url = resolved_base + path
        request_headers = self._build_headers(resolved_base, headers, content_type)
        req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.default_timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except ValueError:
                    return {"error": "Non-JSON response body", "status_code": resp.status}
        except urllib.error.HTTPError as e:
            err_body = {}
            try:
                err_body = json.loads(e.read())
            except Exception:
                pass
            # Prefer the server-provided detail, fall back to the generic HTTP error.
            return {
                "error": err_body.get("detail", str(e)),
                "status_code": e.code,
            }
        except urllib.error.URLError as e:
            return {"error": f"Network error: {e.reason}", "status_code": None}
        except Exception as e:
            return {"error": str(e), "status_code": None}

    def get(self, path: str, base_url: str | None = None,
            headers: dict | None = None, timeout: float | None = None) -> dict:
        return self._request("GET", path, None, base_url, headers, timeout, content_type=None)

    def post(self, path: str, data: dict | None = None, base_url: str | None = None,
             headers: dict | None = None, timeout: float | None = None) -> dict:
        body = json.dumps(data or {}).encode()
        return self._request("POST", path, body, base_url, headers, timeout, content_type="application/json")

    def patch(self, path: str, data: dict, base_url: str | None = None,
              headers: dict | None = None, timeout: float | None = None) -> dict:
        body = json.dumps(data).encode()
        return self._request("PATCH", path, body, base_url, headers, timeout, content_type="application/json")

    def delete(self, path: str, base_url: str | None = None,
               headers: dict | None = None, timeout: float | None = None) -> dict:
        return self._request("DELETE", path, None, base_url, headers, timeout, content_type=None)

    def post_multipart(
        self,
        path: str,
        fields: dict,
        file_data: bytes | None = None,
        filename: str | None = None,
        file_field_name: str = "file",
        file_content_type: str = "application/octet-stream",
        base_url: str | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        """POST multipart/form-data with zero or one file attachment.

        `fields` are sent as plain form parts (stringified). When `file_data`
        is provided, `filename` is required and the part is sent under
        `file_field_name` with `file_content_type`.
        """
        if file_data is not None and not filename:
            raise ValueError("filename is required when file_data is provided")

        boundary = b"urllib_client_boundary_" + os.urandom(8).hex().encode()
        parts: list[bytes] = []
        for key, value in fields.items():
            parts.append(
                b"--" + boundary + b"\r\n"
                b'Content-Disposition: form-data; name="' + str(key).encode() + b'"\r\n\r\n'
                + str(value).encode() + b"\r\n"
            )
        if file_data is not None:
            parts.append(
                b"--" + boundary + b"\r\n"
                b'Content-Disposition: form-data; name="' + file_field_name.encode()
                + b'"; filename="' + filename.encode() + b'"\r\n'
                b"Content-Type: " + file_content_type.encode() + b"\r\n\r\n"
                + file_data + b"\r\n"
            )
        parts.append(b"--" + boundary + b"--\r\n")
        body = b"".join(parts)
        content_type = f"multipart/form-data; boundary={boundary.decode()}"

        return self._request(
            "POST", path, body,
            base_url=base_url,
            headers=headers,
            timeout=timeout or self.multipart_timeout,
            content_type=content_type,
        )
