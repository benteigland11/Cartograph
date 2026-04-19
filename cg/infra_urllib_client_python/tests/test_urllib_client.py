import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import HTTPClient


# ---- Test server ---------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Echo server with programmable responses. Records every request."""
    server_version = "TestHTTP/1.0"
    received: list = []
    responses: dict = {}  # (method, path) -> (status, body_dict)

    def log_message(self, format, *args):
        pass  # silence

    def _record(self, method: str) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        entry = {
            "method": method,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
        }
        type(self).received.append(entry)
        return entry

    def _respond(self, method: str):
        self._record(method)
        status, body = type(self).responses.get((method, self.path.split("?")[0]),
                                                 (200, {"ok": True}))
        body_bytes = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):    self._respond("GET")
    def do_POST(self):   self._respond("POST")
    def do_PATCH(self):  self._respond("PATCH")
    def do_DELETE(self): self._respond("DELETE")


@pytest.fixture
def server():
    _Handler.received = []
    _Handler.responses = {}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = srv.server_address
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, f"http://{host}:{port}", _Handler
    finally:
        srv.shutdown()
        srv.server_close()


# ---- Construction --------------------------------------------------------

def test_rejects_empty_base_url():
    with pytest.raises(ValueError):
        HTTPClient(base_url="")


def test_rejects_none_base_url():
    with pytest.raises(ValueError):
        HTTPClient(base_url=None)


def test_base_url_trailing_slash_stripped():
    c = HTTPClient(base_url="https://api.example.com/")
    assert c.base_url == "https://api.example.com"


# ---- Happy path GET/POST/PATCH/DELETE -----------------------------------

def test_get_returns_json_body(server):
    _, base, H = server
    H.responses[("GET", "/v1/thing")] = (200, {"id": "thing-1", "value": 42})
    c = HTTPClient(base_url=base)
    r = c.get("/v1/thing")
    assert r == {"id": "thing-1", "value": 42}
    assert H.received[0]["method"] == "GET"
    assert H.received[0]["path"] == "/v1/thing"


def test_post_sends_json_body(server):
    _, base, H = server
    H.responses[("POST", "/v1/items")] = (201, {"created": True})
    c = HTTPClient(base_url=base)
    r = c.post("/v1/items", data={"name": "x"})
    assert r == {"created": True}
    sent = json.loads(H.received[0]["body"])
    assert sent == {"name": "x"}
    assert H.received[0]["headers"]["content-type"] == "application/json"


def test_post_empty_body_defaults_to_empty_dict(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.post("/v1/items")
    assert json.loads(H.received[0]["body"]) == {}


def test_patch_sends_json_body(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.patch("/v1/items/1", data={"name": "renamed"})
    assert H.received[0]["method"] == "PATCH"
    assert json.loads(H.received[0]["body"]) == {"name": "renamed"}


def test_delete_returns_body(server):
    _, base, H = server
    H.responses[("DELETE", "/v1/items/1")] = (200, {"deleted": True})
    c = HTTPClient(base_url=base)
    r = c.delete("/v1/items/1")
    assert r == {"deleted": True}
    assert H.received[0]["method"] == "DELETE"


# ---- Auth headers --------------------------------------------------------

def test_auth_headers_called_with_resolved_base(server):
    _, base, H = server
    seen_urls = []
    def auth(url: str) -> dict:
        seen_urls.append(url)
        return {"Authorization": f"Bearer token-for-{url}"}
    c = HTTPClient(base_url=base, auth_headers=auth)
    c.get("/v1/thing")
    assert seen_urls == [base]
    assert H.received[0]["headers"]["authorization"] == f"Bearer token-for-{base}"


def test_auth_headers_failure_silent(server):
    _, base, H = server
    def auth(url: str) -> dict:
        raise RuntimeError("boom")
    c = HTTPClient(base_url=base, auth_headers=auth)
    # Should not raise; just proceeds without auth
    r = c.get("/v1/thing")
    assert "error" not in r
    assert "authorization" not in H.received[0]["headers"]


def test_auth_headers_optional(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.get("/v1/thing")
    assert "authorization" not in H.received[0]["headers"]


# ---- Per-call overrides --------------------------------------------------

def test_per_call_base_url_override(server):
    _, base, H = server
    c = HTTPClient(base_url="http://unused.example.com")
    c.get("/v1/thing", base_url=base)
    assert H.received[0]["path"] == "/v1/thing"


def test_per_call_headers_merge_and_override(server):
    _, base, H = server
    def auth(url): return {"Authorization": "Bearer old", "X-Client": "default"}
    c = HTTPClient(base_url=base, auth_headers=auth)
    c.get("/v1/thing", headers={"Authorization": "Bearer new", "X-Extra": "yes"})
    h = H.received[0]["headers"]
    assert h["authorization"] == "Bearer new"
    assert h["x-client"] == "default"
    assert h["x-extra"] == "yes"


def test_user_agent_sent(server):
    _, base, H = server
    c = HTTPClient(base_url=base, user_agent="my-app/1.0")
    c.get("/v1/thing")
    assert H.received[0]["headers"]["user-agent"] == "my-app/1.0"


# ---- Error handling ------------------------------------------------------

def test_http_error_returns_error_dict(server):
    _, base, H = server
    H.responses[("GET", "/v1/missing")] = (404, {"detail": "not found"})
    c = HTTPClient(base_url=base)
    r = c.get("/v1/missing")
    assert r["error"] == "not found"
    assert r["status_code"] == 404


def test_http_error_falls_back_to_generic_detail(server):
    _, base, H = server
    H.responses[("GET", "/v1/boom")] = (500, {"something": "else"})
    c = HTTPClient(base_url=base)
    r = c.get("/v1/boom")
    assert r["status_code"] == 500
    assert "error" in r


def test_network_error_when_port_unreachable():
    c = HTTPClient(base_url="http://127.0.0.1:1", default_timeout=1.0)
    r = c.get("/anything")
    assert "error" in r
    assert r["status_code"] is None


def test_non_json_response_body(server):
    _, base, H = server
    H.responses[("GET", "/v1/plain")] = (200, b"plain text not json")
    c = HTTPClient(base_url=base)
    r = c.get("/v1/plain")
    assert r["error"] == "Non-JSON response body"
    assert r["status_code"] == 200


def test_empty_body_returns_empty_dict(server):
    _, base, H = server
    H.responses[("GET", "/v1/empty")] = (204, b"")
    c = HTTPClient(base_url=base)
    r = c.get("/v1/empty")
    assert r == {}


# ---- Multipart -----------------------------------------------------------

def test_multipart_fields_only(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.post_multipart("/v1/upload", fields={"name": "x", "kind": "demo"})
    sent = H.received[0]
    ct = sent["headers"]["content-type"]
    assert ct.startswith("multipart/form-data; boundary=")
    body = sent["body"]
    assert b'name="name"' in body
    assert b"x" in body
    assert b'name="kind"' in body
    assert b"demo" in body


def test_multipart_with_file(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.post_multipart(
        "/v1/upload",
        fields={"widget_id": "thing"},
        file_data=b"ZIPBYTES",
        filename="thing.zip",
        file_content_type="application/zip",
    )
    body = H.received[0]["body"]
    assert b'filename="thing.zip"' in body
    assert b"Content-Type: application/zip" in body
    assert b"ZIPBYTES" in body


def test_multipart_custom_file_field_name(server):
    _, base, H = server
    c = HTTPClient(base_url=base)
    c.post_multipart(
        "/v1/upload", fields={}, file_data=b"x", filename="f.bin",
        file_field_name="payload",
    )
    assert b'name="payload"' in H.received[0]["body"]


def test_multipart_file_without_filename_raises(server):
    _, base, _ = server
    c = HTTPClient(base_url=base)
    with pytest.raises(ValueError):
        c.post_multipart("/v1/upload", fields={}, file_data=b"x", filename=None)
