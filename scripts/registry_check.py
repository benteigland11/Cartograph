#!/usr/bin/env python3
"""Registry conformance probe - dev tool, not shipped in the wheel.

Checks a registry implementation against the contract in REGISTRY.md:
prefix handshake, capabilities, search shape + row contract, inspect,
download, and error shape. Read-tier only; write-tier conformance is
exercised by actually publishing.

Usage:
    python scripts/registry_check.py <registry-url> [--query QUERY] [--token TOKEN]

Exit code: 0 all checks pass (warnings allowed), 1 any failure.
"""

import argparse
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# Run from the repo so the CLI's row validator is importable - the probe
# must judge rows with the SAME code the client uses, not a copy.
sys.path.insert(0, "src")
from cartograph.cloud import _validate_widgets  # noqa: E402

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_results = []


def report(status, check, detail=""):
    _results.append(status)
    pad = "" if not detail else f"  {detail}"
    print(f"  [{status}] {check}{pad}")


def fetch(url, token=None, raw=False, timeout=15):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return (body, dict(resp.headers)) if raw else (json.loads(body), dict(resp.headers))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="Registry base URL (e.g. https://registry.example.com)")
    ap.add_argument("--query", default="retry", help="Search term expected to return results")
    ap.add_argument("--token", default=None, help="Bearer token for authenticated checks")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    print(f"\nRegistry conformance: {base}\n")

    # --- 1. Prefix handshake -------------------------------------------------
    prefix = None
    try:
        info, _ = fetch(f"{base}/info", args.token)
        prefix = info.get("prefix")
        if isinstance(prefix, str) and prefix:
            if prefix == "cg":
                report(FAIL, "/info prefix", "'cg' is reserved for the public registry")
            else:
                report(PASS, "/info prefix", f"-> {prefix!r}")
        else:
            report(FAIL, "/info prefix", "missing or non-string 'prefix' field")
    except Exception as e:
        report(FAIL, "GET /info", str(e))

    # --- 2. Capabilities (optional) ------------------------------------------
    try:
        caps, _ = fetch(f"{base}/v1/registry/info", args.token)
        flags = {k: v for k, v in caps.items() if isinstance(v, bool)}
        report(PASS, "/v1/registry/info", json.dumps(flags))
    except Exception:
        report(WARN, "/v1/registry/info", "absent - client assumes validates=false")

    # --- 3. Search shape + row contract --------------------------------------
    rows, first = [], None
    try:
        q = urllib.parse.quote(args.query)
        data, _ = fetch(f"{base}/v1/widgets/search?q={q}&top_k=5", args.token)
        raw_rows = data.get("widgets")
        if not isinstance(raw_rows, list):
            report(FAIL, "search response shape", "expected {'widgets': [...]}")
        else:
            report(PASS, "search response shape", f"{len(raw_rows)} rows")
            if len(raw_rows) > 5:
                report(FAIL, "search top_k", f"asked for 5, got {len(raw_rows)}")
            else:
                report(PASS, "search top_k respected")
            # Judge rows with the client's own validator
            rows = _validate_widgets(list(raw_rows), context="conformance")
            dropped = len(raw_rows) - len(rows)
            if dropped:
                report(FAIL, "widget row contract",
                       f"{dropped}/{len(raw_rows)} rows would be silently dropped by the client")
            elif rows:
                report(PASS, "widget row contract", "all rows valid")
            else:
                report(WARN, "widget row contract",
                       f"no results for query {args.query!r} - try --query")
            for w in rows:
                if "/" not in w.get("id", "") or not w["id"].startswith("@"):
                    report(WARN, "id format", f"{w['id']!r} is not @owner/widget-id")
                    break
            missing = set()
            for w in rows:
                for field in ("name", "domain", "language", "description",
                              "tags", "owner", "dependencies"):
                    if field not in w:
                        missing.add(field)
            if missing:
                report(WARN, "expected row fields", f"missing: {', '.join(sorted(missing))}")
            elif rows:
                report(PASS, "expected row fields present")
            first = rows[0] if rows else None
    except Exception as e:
        report(FAIL, "GET /v1/widgets/search", str(e))

    # --- 4. Inspect -----------------------------------------------------------
    if first:
        owner, wid = first["id"].lstrip("@").split("/", 1)
        try:
            detail, _ = fetch(f"{base}/v1/widgets/{urllib.parse.quote(owner)}/{urllib.parse.quote(wid)}",
                              args.token)
            if detail.get("id") or detail.get("version"):
                report(PASS, "inspect", first["id"])
            else:
                report(FAIL, "inspect", "response missing id/version")
        except Exception as e:
            report(FAIL, "inspect", str(e))

        # --- 5. Download -------------------------------------------------------
        try:
            body, headers = fetch(
                f"{base}/v1/widgets/{urllib.parse.quote(owner)}/{urllib.parse.quote(wid)}/download",
                args.token, raw=True, timeout=60)
            if zipfile.is_zipfile(io.BytesIO(body)):
                report(PASS, "download is a valid zip", f"{len(body)} bytes")
            else:
                report(FAIL, "download", "response body is not a zip")
            lower_headers = {k.lower(): v for k, v in headers.items()}
            for header in ("X-Widget-Version", "X-Widget-Governance"):
                if header.lower() in lower_headers:
                    report(PASS, f"download header {header}", lower_headers[header.lower()])
                else:
                    report(WARN, f"download header {header}", "absent")
        except Exception as e:
            report(FAIL, "download", str(e))
    else:
        report(WARN, "inspect/download", "skipped - no search results to probe with")

    # --- 6. Error shape --------------------------------------------------------
    try:
        fetch(f"{base}/v1/widgets/@nobody-conformance/does-not-exist-xyzzy", args.token)
        report(WARN, "error shape", "bogus widget returned 200 - expected an error status")
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
            if isinstance(err_body.get("error"), str):
                report(PASS, "error shape", f"HTTP {e.code} with JSON 'error' field")
            else:
                report(WARN, "error shape", f"HTTP {e.code} but no JSON 'error' field")
        except Exception:
            report(WARN, "error shape", f"HTTP {e.code} with non-JSON body")
    except Exception as e:
        report(FAIL, "error shape probe", str(e))

    # --- Summary ----------------------------------------------------------------
    fails = _results.count(FAIL)
    warns = _results.count(WARN)
    print(f"\n{len(_results)} checks: {_results.count(PASS)} pass, {warns} warn, {fails} fail\n")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
